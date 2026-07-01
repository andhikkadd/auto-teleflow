import asyncio
from jinja2 import Environment, FileSystemLoader

async def test_render():
    loader = FileSystemLoader('templates')
    env = Environment(loader=loader)
    
    # Mock context variables
    context = {
        "request": None,
        "is_logged_in": True,
        "active_page": "templates",
        "templates": [
            {"id": 10, "text": "app prem murah meriah, aman juga cek bio gasskeun"},
            {"id": 11, "text": "Nonton, musik, edit, desain mulai 1.000an ada di bio"}
        ],
        "override_templates": [],
        "override_active": "0",
        "override_until": "",
        "is_currently_overridden": False,
        "current_time": "2026-07-01T09:32:00",
        "active_tab": "regular",
        "csrf_token": "dummy_csrf"
    }
    
    template = env.get_template("templates.html")
    rendered = template.render(context)
    print("--- RENDER LIST ---")
    start_idx = rendered.find('Saved Templates (Regular)')
    print(rendered[start_idx:start_idx+3500])

if __name__ == '__main__':
    asyncio.run(test_render())
