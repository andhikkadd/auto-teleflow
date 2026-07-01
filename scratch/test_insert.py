import sys
sys.path.append(".")
import sqlite3
from datetime import datetime

def test():
    conn = sqlite3.connect('data/bot.db')
    try:
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        cursor.execute(
            'INSERT INTO groups (username, title, raw_input, is_skipped, status, created_at, updated_at) VALUES (?, ?, ?, 0, "ACTIVE", ?, ?)',
            ('test_group_temp', 'Test Group', 'test_group_temp', now_str, now_str)
        )
        conn.commit()
        print('Insert successful!')
        cursor.execute('DELETE FROM groups WHERE username = ?', ('test_group_temp',))
        conn.commit()
        print('Cleanup successful!')
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    test()
