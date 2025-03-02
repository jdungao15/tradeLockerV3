import sys
from PyQt5.QtWidgets import QApplication
from ui_main import TradingBotUI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TradingBotUI()
    window.show()
    sys.exit(app.exec_())