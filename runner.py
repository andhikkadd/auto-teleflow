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
    tasks = []
    
    # 1. Run Campaigns application
    campaigns_path = os.path.join("campaigns", "main.py")
    tasks.append(run_app(campaigns_path, "campaigns"))
    
    # 2. TODO: Run Assistant application once implemented
    # assistant_path = os.path.join("assistant", "main.py")
    # tasks.append(run_app(assistant_path, "assistant"))
    
    # Run all configured tasks concurrently
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[runner] Shutting down Auto-Teleflow launcher...", flush=True)
