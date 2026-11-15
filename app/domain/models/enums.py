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


class ReviewReason(StrEnum):
    """Why a report line needs a human look. Member order is the order findings are listed in."""

    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_TYPE = "unknown_type"
    UNKNOWN_MATERIAL = "unknown_material"
    CONFLICTING_TYPES = "conflicting_types"
    SIZE_INCONSISTENT = "size_inconsistent"
    SIZE_WITHOUT_SCALE = "size_without_scale"
    COLOR_CONTRADICTS_TYPE = "color_contradicts_type"
    SINGLE_FRAME_ONLY = "single_frame_only"
