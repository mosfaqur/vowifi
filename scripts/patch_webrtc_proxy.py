#!/usr/bin/env python3
"""
patch_webrtc_proxy.py
Idempotently adds a WebSocket reverse proxy for WebRTC SIP traffic into vowifi-control:
1. control/app/main.py:
   - Exposes @app.websocket("/api/instances/{iid}/webrtc/ws") proxying WSS to Asterisk on localhost.
   - Updates api_softphone to return "ws_path": "/api/instances/{iid}/webrtc/ws".
2. webui/src/softphone.js:
   - Supports connecting to prov.ws_path over standard port 443 (same host/protocol as WebUI).
3. webui/dist/assets/index-SakEcPCY.js:
   - Patches compiled softphone client to use prov.ws_path when provided.
"""

import sys
import os
import re


def patch_main_py(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # 1. Ensure imports: ssl, websockets
    if "import ssl" not in content:
        content = content.replace("import asyncio\n", "import asyncio\nimport ssl\nimport websockets\n", 1)
        modified = True
        print(f" [+] Added ssl and websockets imports to {path}.")

    # 2. Update api_softphone to return ws_path
    if '"ws_path"' not in content:
        target = '"ws_port": ports.get("webrtc", 8089),\n'
        replacement = (
            '"ws_port": ports.get("webrtc", 8089),\n'
            '        "ws_path": f"/api/instances/{iid}/webrtc/ws",\n'
        )
        if target in content:
            content = content.replace(target, replacement, 1)
            modified = True
            print(f" [+] Added ws_path to api_softphone in {path}.")

    # 3. Add webrtc_ws_proxy endpoint
    if "async def webrtc_ws_proxy" not in content:
        proxy_code = (
            "\n\n@app.websocket(\"/api/instances/{iid}/webrtc/ws\")\n"
            "async def webrtc_ws_proxy(ws: WebSocket, iid: str):\n"
            "    \"\"\"Proxy WebRTC SIP WebSocket traffic between browser softphone and Asterisk.\"\"\"\n"
            "    inst = cfg.get_instance(iid)\n"
            "    if not inst:\n"
            "        await ws.close(code=1008)\n"
            "        return\n"
            "\n"
            "    subprotocol = \"sip\" if \"sip\" in ws.headers.get(\"sec-websocket-protocol\", \"\") else None\n"
            "    await ws.accept(subprotocol=subprotocol)\n"
            "\n"
            "    ports = inst.get(\"ports\", {})\n"
            "    ws_port = ports.get(\"webrtc\", 8089)\n"
            "\n"
            "    ssl_ctx = ssl.create_default_context()\n"
            "    ssl_ctx.check_hostname = False\n"
            "    ssl_ctx.verify_mode = ssl.CERT_NONE\n"
            "\n"
            "    try:\n"
            "        async with websockets.connect(\n"
            "            f\"wss://127.0.0.1:{ws_port}/ws\",\n"
            "            ssl=ssl_ctx,\n"
            "            subprotocols=[\"sip\"] if subprotocol else None,\n"
            "            ping_interval=20,\n"
            "            ping_timeout=20,\n"
            "            max_size=None,\n"
            "        ) as ast_ws:\n"
            "            async def client_to_ast():\n"
            "                try:\n"
            "                    while True:\n"
            "                        data = await ws.receive()\n"
            "                        if data[\"type\"] == \"websocket.receive\":\n"
            "                            if \"text\" in data and data[\"text\"]:\n"
            "                                await ast_ws.send(data[\"text\"])\n"
            "                            elif \"bytes\" in data and data[\"bytes\"]:\n"
            "                                await ast_ws.send(data[\"bytes\"])\n"
            "                        elif data[\"type\"] == \"websocket.disconnect\":\n"
            "                            break\n"
            "                except Exception:\n"
            "                    pass\n"
            "\n"
            "            async def ast_to_client():\n"
            "                try:\n"
            "                    while True:\n"
            "                        msg = await ast_ws.recv()\n"
            "                        if isinstance(msg, bytes):\n"
            "                            await ws.send_bytes(msg)\n"
            "                        else:\n"
            "                            await ws.send_text(msg)\n"
            "                except Exception:\n"
            "                    pass\n"
            "\n"
            "            done, pending = await asyncio.wait(\n"
            "                [asyncio.create_task(client_to_ast()), asyncio.create_task(ast_to_client())],\n"
            "                return_when=asyncio.FIRST_COMPLETED,\n"
            "            )\n"
            "            for t in pending:\n"
            "                t.cancel()\n"
            "    except Exception as e:\n"
            "        log.warning(f\"webrtc_ws_proxy failed for instance {iid}: {e}\")\n"
            "        try:\n"
            "            await ws.close(code=1011)\n"
            "        except Exception:\n"
            "            pass\n"
        )
        # Place before static WebUI mount
        marker = "# ----------------------------- static WebUI -----------------------------"
        if marker in content:
            content = content.replace(marker, proxy_code + "\n\n" + marker, 1)
            modified = True
            print(f" [+] Added webrtc_ws_proxy WebSocket endpoint to {path}.")
        else:
            content += proxy_code
            modified = True
            print(f" [+] Appended webrtc_ws_proxy WebSocket endpoint to {path}.")

    # 4. Add no-cache header to SPA index.html delivery to prevent stale cache on reverse proxies
    target_spa = 'if os.path.isfile(index):\n            return FileResponse(index)'
    repl_spa = 'if os.path.isfile(index):\n            return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})'
    if target_spa in content:
        content = content.replace(target_spa, repl_spa, 1)
        modified = True
        print(f" [+] Added no-cache header for index.html to {path}.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {path}.")
        return True
    else:
        print(f" [.] {path} is already up-to-date.")
        return False


def patch_softphone_src(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    target = "    const wsUrl = `wss://${host}:${prov.ws_port}/ws`\n"
    replacement = (
        "    const proto = location.protocol === 'https:' ? 'wss' : 'ws'\n"
        "    const wsUrl = prov.ws_path ? `${proto}://${location.host}${prov.ws_path}` : `wss://${host}:${prov.ws_port}/ws`\n"
    )

    if target in content:
        content = content.replace(target, replacement, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Patched softphone source {path}.")
        return True
    else:
        print(f" [.] {path} is already up-to-date.")
        return False


def patch_webui_dist(dist_dir):
    if not os.path.exists(dist_dir):
        return False
    modified = False
    for root, _, files in os.walk(dist_dir):
        for f in files:
            if f.endswith(".js"):
                fp = os.path.join(root, f)
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    c = fh.read()
                old = "const E=`wss://${o}:${g.ws_port}/ws`,w=new Zu.WebSocketInterface(E)"
                new = "const E=g.ws_path?`${location.protocol===\"https:\"?\"wss\":\"ws\"}://${location.host}${g.ws_path}`:`wss://${o}:${g.ws_port}/ws`,w=new Zu.WebSocketInterface(E)"
                if old in c:
                    c = c.replace(old, new)
                    with open(fp, "w", encoding="utf-8") as fh:
                        fh.write(c)
                    print(f" [+] Patched compiled WebUI asset {fp}.")
                    modified = True

    # Cache buster: copy patched JS to index-v2.js and update index.html
    html_path = os.path.join(dist_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as fh:
            html = fh.read()
        if "index-v2.js" not in html:
            # find original asset name
            m = re.search(r'assets/(index-[^"]+\.js)', html)
            if m:
                orig_name = m.group(1)
                orig_path = os.path.join(dist_dir, "assets", orig_name)
                v2_path = os.path.join(dist_dir, "assets", "index-v2.js")
                if os.path.exists(orig_path):
                    import shutil
                    shutil.copy2(orig_path, v2_path)
                    print(f" [+] Created cache-busted asset {v2_path}.")
                html = html.replace(orig_name, "index-v2.js", 1)
                with open(html_path, "w", encoding="utf-8") as fh:
                    fh.write(html)
                print(f" [+] Updated {html_path} to use index-v2.js.")
                modified = True

    return modified


def main():
    target_root = sys.argv[1] if len(sys.argv) > 1 else "/root/vowifi_gateway"

    main_py = os.path.join(target_root, "control/app/main.py")
    softphone_src = os.path.join(target_root, "webui/src/softphone.js")
    dist_dir = os.path.join(target_root, "webui/dist")

    patch_main_py(main_py)
    patch_softphone_src(softphone_src)
    patch_webui_dist(dist_dir)


if __name__ == "__main__":
    main()
