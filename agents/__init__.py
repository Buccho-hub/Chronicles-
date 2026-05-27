"""agents/__init__.py"""
from agents.solomon         import SolomonAgent
from agents.daniel          import DanielAgent
from agents.amos            import AmosAgent
from agents.ruth            import RuthAgent
from agents.john            import JohnAgent
from agents.augustine       import AugustineAgent
from agents.marcus_aurelius import MarcusAureliusAgent
from agents.hildegard       import HildegardAgent
from agents.cassandra       import CassandraAgent

ALL_AGENTS = [
    SolomonAgent(),
    DanielAgent(),
    AmosAgent(),
    RuthAgent(),
    JohnAgent(),
    AugustineAgent(),
    MarcusAureliusAgent(),
    HildegardAgent(),
    CassandraAgent(),
]

AGENT_MAP = {a.name: a for a in ALL_AGENTS}
