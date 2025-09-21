#!/usr/bin/env bash
# =============================================================================
# collect_metrics.sh
# -----------------------------------------------------------------------------
# Collates all lines mentioning Prometheus-style metrics (mcp_*) from
# mcp_server/*.py and mcp_server/tools/*.py into a single output file.
# =============================================================================

OUTPUT_FILE="metrics_references.txt"

# Remove old output if it exists
rm -f "$OUTPUT_FILE"

# Search for all lines containing "mcp_" in the Python sources
# -n : show line numbers
# -H : show filename
# -i : case-insensitive (optional, in case of mixed case)
# -r : recursive
# egrep : extended regex
egrep -rinH "mcp_" mcp_server/*.py mcp_server/tools/*.py > "$OUTPUT_FILE"

echo "✅ Metrics references collected into $OUTPUT_FILE"
