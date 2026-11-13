from enum import StrEnum


class UtilityType(StrEnum):
    GAS = "gas"
    WATER = "water"
    WASTEWATER = "wastewater"
    DISTRICT_HEATING = "district_heating"
    POWER = "power"
    TELECOM = "telecom"
    UNKNOWN = "unknown"


class Material(StrEnum):
    PE = "pe"
    PVC_PP = "pvc_pp"
    STEEL = "steel"
    CAST_IRON = "cast_iron"
    CONCRETE = "concrete"
    PRE_INSULATED = "pre_insulated"
    CABLE = "cable"
    UNKNOWN = "unknown"


class JobStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    CONSOLIDATING = "consolidating"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
