import asyncio
import sys
import os

async def stream_output(stream, prefix):
    """Asynchronously read lines from a stream and print with a prefix."""
    while True:
        line = await stream.readline()
        if not line:
            break
        try:
            decoded_line = line.decode('utf-8', errors='replace').rstrip('\r\n')
            print(f"{prefix} {decoded_line}", flush=True)
        except Exception:
            pass

async def run_app(path, name):
    """Run a sub-application using the current Python interpreter."""
    prefix = f"[{name}]"
    print(f"Starting application: {name} ({path})...", flush=True)
    
    # Resolve absolute path for working directory
    working_dir = os.path.dirname(os.path.abspath(path))
    script_name = os.path.basename(path)
    
    process = await asyncio.create_subprocess_exec(
        sys.executable, script_name,
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Start concurrent streaming of stdout and stderr
    await asyncio.gather(
        stream_output(process.stdout, prefix),
        stream_output(process.stderr, prefix)
    )
    
    return_code = await process.wait()
    print(f"Application {name} terminated with return code {return_code}", flush=True)

async def main():
    # Fetch and print the actual public IP of the VPS Node
    import urllib.request
    try:
        public_ip = urllib.request.urlopen('https://api.ipify.org', timeout=5).read().decode('utf-8').strip()
        print(f"\n[runner] VPS NODE PUBLIC IP: {public_ip}", flush=True)
        print(f"[runner] DIRECT PANEL URL: http://{public_ip}:4765\n", flush=True)
    except Exception as e:
        print(f"[runner] Failed to resolve public VPS IP: {e}", flush=True)
        
    tasks = []
    
    # 1. Run Campaigns application
    campaigns_path = "main.py"
    tasks.append(run_app(campaigns_path, "app"))
    
    # 4. Run automated free SSH tunnel (pinggy.io) if ssh client is available
    import shutil
    if shutil.which("ssh"):
        print("[runner] SSH client detected. Initiating secure web tunnel via pinggy.io...", flush=True)
        async def run_tunnel():
            tunnel_cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no", 
                "-o", "ServerAliveInterval=30", 
                "-R", "80:127.0.0.1:4765", "free@pinggy.io"
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *tunnel_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    decoded_line = line.decode('utf-8', errors='replace').rstrip('\r\n')
                    if "http://" in decoded_line or "https://" in decoded_line:
                        print(f"\n[tunnel] PUBLIC WEB PANEL URL: {decoded_line.strip()}\n", flush=True)
                    elif any(k in decoded_line.lower() for k in ["pinggy", "tunnel", "connected"]):
                        print(f"[tunnel] {decoded_line.strip()}", flush=True)
            except Exception as e:
                print(f"[tunnel] Failed to start tunnel: {e}", flush=True)
        tasks.append(run_tunnel())
    else:
        print("[runner] SSH client not available in this container. Bypassing public tunnel.", flush=True)
    
    # Run all configured tasks concurrently
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[runner] Shutting down Auto-Teleflow launcher...", flush=True)
