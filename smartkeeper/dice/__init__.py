"""掷骰的随机源。随机数只在这里产生，由 engine 调用并写入事件日志；骰子公式的解析在 rules。"""

from smartkeeper.dice.roller import DiceRoller, SeededRandomSource, SystemRandomSource

__all__ = ["DiceRoller", "SeededRandomSource", "SystemRandomSource"]
