"""EpiRefine-HPC: heterostructure analysis and adaptive epitaxial sampling."""

from .api import (
    AdaptiveProposalRequest,
    InterfaceMatchRequest,
    ToolUnavailableError,
    VaspkitExtractionRequest,
    VolumeSliceRequest,
    analyze_interface,
    configure_external_tool,
    extract_vaspkit_volumes,
    marker_from_match,
    plot_contours,
    propose_iteration,
    render_volume_slice,
    run_hstructpy,
    tool_status,
    tool_registry_path,
    write_interface_report,
)

__all__ = [
    "AdaptiveProposalRequest", "InterfaceMatchRequest", "ToolUnavailableError",
    "VaspkitExtractionRequest",
    "VolumeSliceRequest", "analyze_interface", "marker_from_match", "plot_contours",
    "configure_external_tool", "extract_vaspkit_volumes", "propose_iteration",
    "render_volume_slice", "run_hstructpy", "tool_status", "tool_registry_path",
    "write_interface_report",
]

__version__ = "0.4.0"
