from krita import Krita
from .rebelsrule import RebelsRuleExtension

Krita.instance().addExtension(RebelsRuleExtension(Krita.instance()))
