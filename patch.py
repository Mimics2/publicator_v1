import sys
from unittest.mock import MagicMock

# Создаем мок для imghdr
mock_imghdr = MagicMock()
mock_imghdr.what = lambda x: None

sys.modules['imghdr'] = mock_imghdr
