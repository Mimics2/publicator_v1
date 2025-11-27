import sys
sys.modules['imghdr'] = type('MockImghdr', (), {'what': lambda x: None})()
