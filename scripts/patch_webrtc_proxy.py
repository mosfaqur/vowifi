#!/usr/bin/env python3
"""
patch_webrtc_proxy.py
Idempotently adds a WebSocket reverse proxy for WebRTC SIP traffic and fixes WebRTC audio:
1. control/app/main.py:
   - Exposes @app.websocket("/api/instances/{iid}/webrtc/ws") proxying WSS to Asterisk on localhost.
   - Updates api_softphone to return "ws_path": "/api/instances/{iid}/webrtc/ws".
   - Adaptive ice_servers: returns empty [] for LAN/local clients (direct LAN WebRTC without loopback failure)
     and STUN for remote domain clients.
2. webui/src/softphone.js:
   - Fixes unlockAudio() race condition (removes asynchronous el.pause() that muted active call audio).
   - Fixes ensureAudio() to avoid display:none (which causes browser audio throttling/muting).
   - Uses adaptive ice_servers from provisioning.
3. webui/src/views/Softphone.jsx:
   - Sets non-blocking fixed offscreen positioning on the <audio> tag instead of display:none.
4. webui/dist/assets/index-v4.js:
   - Patches compiled softphone client and cache-busts index.html to index-v4.js.
5. engine/templates/rtp.conf.j2 & extensions.conf.j2:
   - Removes stunaddr to prevent IPv6 IMS STUN failure and ensure clean LAN ICE host candidate pairing.
   - Changes Return() to Hangup() in hangup handler.
"""

import sys
import os
import re
import shutil


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

    # 2. Update api_softphone with adaptive ice_servers and ws_path
    target_pattern = r'def api_softphone\(iid: str, request: Request\):.*?(return \{.*?\n    \})'
    m = re.search(r'def api_softphone\(iid: str, request: Request\):.*?(?=\n\n@|\Z)', content, re.DOTALL)
    if m:
        old_body = m.group(0)
        new_body = (
            'def api_softphone(iid: str, request: Request):\n'
            '    """Provisioning for the browser softphone (JsSIP over WSS)."""\n'
            '    inst = cfg.get_instance(iid)\n'
            '    if not inst:\n'
            '        raise HTTPException(404, "no such instance")\n'
            '    sip = inst.get("sip", {}) or {}\n'
            '    wr = sip.get("webrtc", {}) or {}\n'
            '    ports = inst.get("ports", {})\n'
            '    host = (request.headers.get("host") or "").split(":")[0] or request.url.hostname\n'
            '    is_lan = (\n'
            '        host in ("localhost", "127.0.0.1", "::1")\n'
            '        or host.startswith("192.168.")\n'
            '        or host.startswith("10.")\n'
            '        or host.startswith("172.")\n'
            '    )\n'
            '    ice_servers = [] if is_lan else [\n'
            '        {"urls": "stun:stun.l.google.com:19302"},\n'
            '        {"urls": "stun:stun1.l.google.com:19302"},\n'
            '    ]\n'
            '    return {\n'
            '        "enabled": bool(wr.get("enable", True)),\n'
            '        "username": wr.get("username", "webrtc"),\n'
            '        "password": wr.get("password", ""),\n'
            '        "ws_port": ports.get("webrtc", 8089),\n'
            '        "ws_path": f"/api/instances/{iid}/webrtc/ws",\n'
            '        "host": host,\n'
            '        "realm": cfg.ims_realm(inst["mcc"], inst["mnc"]),\n'
            '        "ice_servers": ice_servers,\n'
            '    }'
        )
        if old_body != new_body:
            content = content.replace(old_body, new_body, 1)
            modified = True
            print(f" [+] Updated api_softphone in {path} with adaptive ice_servers.")

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

        target = "if os.path.isdir(WEBUI_DIR):"
        if target in content:
            content = content.replace(target, proxy_code + "\n\n# ----------------------------- static WebUI -----------------------------\n" + target, 1)
            modified = True
            print(f" [+] Added webrtc_ws_proxy to {path}.")

    # 4. Ensure no-cache headers on SPA delivery
    if "response.headers[\"Cache-Control\"]" not in content:
        spa_target = "        if os.path.isfile(index):\n            return FileResponse(index)\n"
        spa_replacement = (
            "        if os.path.isfile(index):\n"
            "            response = FileResponse(index)\n"
            "            response.headers[\"Cache-Control\"] = \"no-cache, no-store, must-revalidate\"\n"
            "            return response\n"
        )
        if spa_target in content:
            content = content.replace(spa_target, spa_replacement, 1)
            modified = True
            print(f" [+] Added no-cache headers to SPA handler in {path}.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {path}.")
        return True
    return False


def patch_softphone_src(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # 1. wsUrl
    target = "    const wsUrl = `wss://${host}:${prov.ws_port}/ws`\n"
    replacement = (
        "    const proto = location.protocol === 'https:' ? 'wss' : 'ws'\n"
        "    const wsUrl = prov.ws_path ? `${proto}://${location.host}${prov.ws_path}` : `wss://${host}:${prov.ws_port}/ws`\n"
    )
    if target in content:
        content = content.replace(target, replacement, 1)
        modified = True

    # 2. prov assignment
    if "this.prov = prov" not in content:
        content = content.replace("start(prov, host) {\n    if (this.ua) this.stop()", "start(prov, host) {\n    if (this.ua) this.stop()\n    this.prov = prov", 1)
        modified = True

    # 3. unlockAudio fix: do not pause audio element asynchronously
    old_unlock = (
        "  unlockAudio() {\n"
        "    if (this._unlocked) return\n"
        "    const el = this.ensureAudio()\n"
        "    try {\n"
        "      el.muted = true\n"
        "      const p = el.play()\n"
        "      if (p && p.then) p.then(() => { try { el.pause(); el.currentTime = 0 } catch {} el.muted = false })\n"
        "                        .catch(() => { el.muted = false })\n"
        "      else { try { el.pause() } catch {}; el.muted = false }\n"
        "      this._unlocked = true\n"
        "    } catch { el.muted = false }\n"
        "  }"
    )
    new_unlock = (
        "  unlockAudio() {\n"
        "    if (this._unlocked) return\n"
        "    const el = this.ensureAudio()\n"
        "    try {\n"
        "      el.muted = false\n"
        "      const Ctx = window.AudioContext || window.webkitAudioContext\n"
        "      if (Ctx) {\n"
        "        if (!this._audioCtx) this._audioCtx = new Ctx()\n"
        "        if (this._audioCtx.state === 'suspended') this._audioCtx.resume().catch(() => {})\n"
        "      }\n"
        "      this._unlocked = true\n"
        "    } catch {}\n"
        "  }"
    )
    if old_unlock in content:
        content = content.replace(old_unlock, new_unlock, 1)
        modified = True

    # 4. ensureAudio fix: avoid display: none
    old_ensure = "      el.style.display = 'none'\n"
    new_ensure = (
        "      el.style.position = 'fixed'\n"
        "      el.style.top = '-9999px'\n"
        "      el.style.left = '-9999px'\n"
        "      el.style.width = '1px'\n"
        "      el.style.height = '1px'\n"
        "      el.style.opacity = '0'\n"
        "      el.style.pointerEvents = 'none'\n"
    )
    if old_ensure in content:
        content = content.replace(old_ensure, new_ensure, 1)
        modified = True

    # 5. iceServers in call and answer
    content = re.sub(
        r'pcConfig:\s*\{\s*rtcpMuxPolicy:\s*[\'"]require[\'"],\s*iceServers:.*?\n\s*\}',
        "pcConfig: { rtcpMuxPolicy: 'require', iceServers: (this.prov && this.prov.ice_servers != null) ? this.prov.ice_servers : [] }",
        content
    )
    content = re.sub(
        r'pcConfig:\s*\{\s*rtcpMuxPolicy:\s*[\'"]require[\'"],\s*iceServers:.*?\}\s*\}',
        "pcConfig: { rtcpMuxPolicy: 'require', iceServers: (this.prov && this.prov.ice_servers != null) ? this.prov.ice_servers : [] } }",
        content
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f" [+] Patched softphone source {path}.")
    return True


def patch_softphone_view(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False
    old_tag = '<audio ref={audioRef} autoPlay playsInline style={{ display: \'none\' }} />'
    new_tag = '<audio ref={audioRef} autoPlay playsInline style={{ position: \'fixed\', top: -9999, left: -9999, width: 1, height: 1, opacity: 0, pointerEvents: \'none\' }} />'
    if old_tag in content:
        content = content.replace(old_tag, new_tag, 1)
        modified = True
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Patched Softphone.jsx audio tag in {path}.")
    return modified


def patch_webui_dist(dist_dir):
    if not os.path.exists(dist_dir):
        return False

    assets_dir = os.path.join(dist_dir, "assets")
    orig_path = os.path.join(assets_dir, "index-SakEcPCY.js")
    if not os.path.exists(orig_path):
        # find any index-*.js that is original
        for fn in os.listdir(assets_dir):
            if fn.startswith("index-") and fn.endswith(".js") and fn not in ("index-v2.js", "index-v3.js", "index-v4.js"):
                orig_path = os.path.join(assets_dir, fn)
                break

    with open(orig_path, "r", encoding="utf-8") as f:
        c = f.read()

    # 1. WSS path
    old_ws = 'const E=`wss://${o}:${g.ws_port}/ws`,w=new Zu.WebSocketInterface(E)'
    new_ws = 'const E=g.ws_path?`${location.protocol==="https:"?"wss":"ws"}://${location.host}${g.ws_path}`:`wss://${o}:${g.ws_port}/ws`,w=new Zu.WebSocketInterface(E)'
    if old_ws in c:
        c = c.replace(old_ws, new_ws, 1)

    # 2. Store prov in start(g, o)
    old_start = 'start(g,o){this.ua&&this.stop();'
    new_start = 'start(g,o){this.prov=g;this.ua&&this.stop();'
    if old_start in c:
        c = c.replace(old_start, new_start, 1)

    # 3. Ice servers & rtcpMuxPolicy in call and answer
    c = c.replace('pcConfig:{rtcpMuxPolicy:"require",iceServers:[]}', 'pcConfig:{rtcpMuxPolicy:"require",iceServers:(this.prov&&this.prov.ice_servers!=null?this.prov.ice_servers:[])}')
    c = c.replace('pcConfig:{iceServers:[]}', 'pcConfig:{rtcpMuxPolicy:"require",iceServers:(this.prov&&this.prov.ice_servers!=null?this.prov.ice_servers:[])}')

    # 4. ensureAudio cssText (avoid display:none)
    old_ea = 'g.style.display="none"'
    new_ea = 'g.style.cssText="position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none"'
    if old_ea in c:
        c = c.replace(old_ea, new_ea, 1)

    # 5. unlockAudio without pausing
    old_ua = 'try{g.muted=!0;const o=g.play();if(o&&o.then)o.then(()=>{try{g.pause(),g.currentTime=0}catch{}g.muted=!1}).catch(()=>{g.muted=!1});else{try{g.pause()}catch{};g.muted=!1}this._unlocked=!0}catch{g.muted=!1}'
    new_ua = 'try{g.muted=!1;const C=window.AudioContext||window.webkitAudioContext;if(C){if(!this._ctx)this._ctx=new C;if(this._ctx.state==="suspended")this._ctx.resume().catch(()=>{})}this._unlocked=!0}catch{}'
    if old_ua in c:
        c = c.replace(old_ua, new_ua, 1)

    # 6. React audio tag style
    old_tag = 'playsInline:!0,style:{display:"none"}}'
    new_tag = 'playsInline:!0,style:{position:"fixed",top:-9999,left:-9999,width:1,height:1,opacity:0,pointerEvents:"none"}}'
    if old_tag in c:
        c = c.replace(old_tag, new_tag, 1)

    v4_path = os.path.join(assets_dir, "index-v4.js")
    with open(v4_path, "w", encoding="utf-8") as f:
        f.write(c)
    print(f" [+] Generated cache-busted asset {v4_path}.")

    # Update index.html to point to index-v4.js
    html_path = os.path.join(dist_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        html = re.sub(r'index-[^"]+\.js', 'index-v4.js', html)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f" [+] Updated {html_path} to reference index-v4.js.")

    return True


def patch_rtp_template(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False
    if "stunaddr=" in content:
        lines = [line for line in content.splitlines(True) if not line.strip().startswith("stunaddr=")]
        content = "".join(lines)
        modified = True
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Removed stunaddr from {path} to ensure LAN host candidates & prevent IPv6 STUN errors.")
    return modified


def patch_extensions_template(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False
    if "same => n,Return()" in content:
        content = content.replace("same => n,Return()", "same => n,Hangup()")
        modified = True
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Replaced Return() with Hangup() in {path}.")
    return modified


def main():
    target_root = sys.argv[1] if len(sys.argv) > 1 else "/root/vowifi_gateway"

    main_py = os.path.join(target_root, "control/app/main.py")
    softphone_src = os.path.join(target_root, "webui/src/softphone.js")
    softphone_view = os.path.join(target_root, "webui/src/views/Softphone.jsx")
    dist_dir = os.path.join(target_root, "webui/dist")
    rtp_j2 = os.path.join(target_root, "engine/templates/rtp.conf.j2")
    ext_j2 = os.path.join(target_root, "engine/templates/extensions.conf.j2")

    patch_main_py(main_py)
    patch_softphone_src(softphone_src)
    patch_softphone_view(softphone_view)
    patch_webui_dist(dist_dir)
    patch_rtp_template(rtp_j2)
    patch_extensions_template(ext_j2)


if __name__ == "__main__":
    main()
