"""agents/__init__.py"""
from agents.solomon        import SolomonAgent
from agents.daniel         import DanielAgent
from agents.amos           import AmosAgent
from agents.ruth           import RuthAgent
from agents.john           import JohnAgent
from agents.augustine      import AugustineAgent
from agents.marcus_aurelius import MarcusAureliusAgent
from agents.hildegard      import HildegardAgent

ALL_AGENTS = [
    SolomonAgent(),
    DanielAgent(),
    AmosAgent(),
    RuthAgent(),
    JohnAgent(),
    AugustineAgent(),
    MarcusAureliusAgent(),
    HildegardAgent(),
]

AGENT_MAP = {a.name: a for a in ALL_AGENTS}
