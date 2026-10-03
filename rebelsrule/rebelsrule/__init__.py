from krita import Krita
from .extension import RebelsRuleExtension

Krita.instance().addExtension(RebelsRuleExtension(Krita.instance()))
