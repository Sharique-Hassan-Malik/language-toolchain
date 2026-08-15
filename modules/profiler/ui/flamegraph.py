"""
Generates a self-contained interactive flame graph HTML file.

The output is a single .html page with:
    - An inline SVG flame graph
    - JavaScript for hover tooltips, click-to-zoom and breadcrumb navigation
    - A search box to highlight matching frames
    - A summary statistics panel
    - No external dependencies

The flame graph is rendered top-down: root at the top, hot path descending.
Each rectangle's width is proportional to its total_samples count.
Colour is based on the function's filename to group related frames visually.
"""

from __future__ import annotations

import hashlib
import json
import math

from profiler.aggregator import FlameNode, FlameRoot


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

def _frame_colour(filename: str, is_highlighted: bool = False) -> str:
    """Deterministic HSL colour based on the source filename."""
    digest = int(hashlib.md5(filename.encode()).hexdigest()[:8], 16)
    hue    = digest % 360
    return f"hsl({hue}, 60%, 55%)"


# ---------------------------------------------------------------------------
# SVG layout engine
# ---------------------------------------------------------------------------

_FRAME_HEIGHT = 20   # px per row
_MIN_WIDTH    = 2    # px — frames narrower than this are skipped


class FlamegraphRenderer:
    """
    Renders a FlameRoot into a self-contained interactive HTML page.

    The algorithm:
        1. Compute the total width budget from root.total_samples.
        2. Depth-first assign x-offset and width to each node proportionally.
        3. Emit one SVG <rect> + <text> per visible node.
        4. Inline JavaScript handles hover, zoom, search and stats.
    """

    def __init__(self, width: int = 1200, min_width_px: int = _MIN_WIDTH):
        self.width       = width
        self.min_width   = min_width_px

    def render(
        self,
        root: FlameRoot,
        title: str = "Flame Graph",
        sample_interval_ms: float = 1.0,
    ) -> str:
        rects = self._layout(root)
        max_depth = max((r["depth"] for r in rects), default=0)
        height = (max_depth + 3) * _FRAME_HEIGHT + 80   # +80 for header/footer

        svg_content  = self._build_svg(rects, height, root.total_samples)
        stats_html   = self._build_stats(root, sample_interval_ms)
        js           = _JS_TEMPLATE
        css          = _CSS_TEMPLATE

        data_json = json.dumps([
            {
                "id":    r["id"],
                "name":  r["name"],
                "file":  r["filename"],
                "line":  r["lineno"],
                "total": r["total"],
                "self":  r["self"],
                "pct":   r["pct"],
            }
            for r in rects
        ])

        return _HTML_TEMPLATE.format(
            title=title,
            css=css,
            svg=svg_content,
            stats=stats_html,
            js=js,
            data_json=data_json,
            total_samples=root.total_samples,
        )

    # ── Layout ────────────────────────────────────────────────────────────

    def _layout(self, root: FlameRoot) -> list[dict]:
        rects = []
        total = max(root.total_samples, 1)
        node_id = [0]

        def visit(children: dict, x_offset: float, depth: int, parent_width: float):
            # Sort children by total_samples descending so wider blocks come first
            for frame, node in sorted(
                children.items(), key=lambda kv: -kv[1].total_samples
            ):
                w = (node.total_samples / total) * self.width
                if w < self.min_width:
                    continue

                pct = node.total_samples / total * 100
                nid = node_id[0]
                node_id[0] += 1

                rects.append({
                    "id":       nid,
                    "x":        x_offset,
                    "depth":    depth,
                    "width":    w,
                    "name":     node.name,
                    "filename": node.frame.filename,
                    "lineno":   node.frame.lineno,
                    "funcname": node.frame.funcname,
                    "total":    node.total_samples,
                    "self":     node.self_samples,
                    "pct":      pct,
                    "colour":   _frame_colour(node.frame.filename),
                })

                if node.children:
                    visit(node.children, x_offset, depth + 1, w)

                x_offset += w

        visit(root.children, 0, 0, self.width)
        return rects

    # ── SVG building ──────────────────────────────────────────────────────

    def _build_svg(
        self, rects: list[dict], height: int, total_samples: int
    ) -> str:
        lines = [
            f'<svg id="flamegraph" width="{self.width}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
        ]

        for r in rects:
            y      = r["depth"] * _FRAME_HEIGHT + 40
            x      = r["x"]
            w      = r["width"]
            colour = r["colour"]
            label  = r["funcname"]
            nid    = r["id"]

            # Truncate label to fit in the rectangle
            max_chars = max(1, int(w / 7))
            if len(label) > max_chars:
                label = label[: max(1, max_chars - 1)] + "…"

            lines.append(
                f'<g class="frame" data-id="{nid}" '
                f'data-name="{_esc(r["name"])}" '
                f'data-file="{_esc(r["filename"])}" '
                f'data-line="{r["lineno"]}" '
                f'data-total="{r["total"]}" '
                f'data-self="{r["self"]}" '
                f'data-pct="{r["pct"]:.1f}">'
            )
            lines.append(
                f'  <rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{_FRAME_HEIGHT - 1}" '
                f'fill="{colour}" stroke="white" stroke-width="0.5" rx="1"/>'
            )
            if w > 20:
                lines.append(
                    f'  <text x="{x + 3:.2f}" y="{y + 13}" '
                    f'font-size="11" fill="white" clip-path="url(#clip-{nid})">'
                    f'{_esc(label)}</text>'
                )
                lines.append(
                    f'  <clipPath id="clip-{nid}">'
                    f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{_FRAME_HEIGHT}"/>'
                    f'</clipPath>'
                )
            lines.append("</g>")

        lines.append("</svg>")
        return "\n".join(lines)

    def _build_stats(self, root: FlameRoot, interval_ms: float) -> str:
        from profiler.aggregator import Aggregator
        top = Aggregator.hottest_functions(root, n=10)
        rows = ""
        total = max(root.total_samples, 1)
        for node in top:
            pct   = node.self_samples / total * 100
            ms    = node.self_samples * interval_ms
            rows += (
                f"<tr><td>{_esc(node.frame.funcname)}</td>"
                f"<td>{_esc(node.frame.filename.split('/')[-1])}</td>"
                f"<td>{node.frame.lineno}</td>"
                f"<td>{pct:.1f}%</td>"
                f"<td>{ms:.1f} ms</td></tr>\n"
            )
        return f"""
        <h3>Top Functions by Self Time</h3>
        <table class="stats">
          <thead><tr>
            <th>Function</th><th>File</th><th>Line</th>
            <th>Self %</th><th>Self ms</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
        <p class="meta">Total samples: {root.total_samples} &nbsp;|&nbsp;
           Interval: {interval_ms:.1f} ms</p>
        """


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Embedded templates
# ---------------------------------------------------------------------------

_CSS_TEMPLATE = """
body { font-family: monospace; background: #1e1e2e; color: #cdd6f4; margin: 0; padding: 0; }
h1   { font-size: 1.2em; padding: 10px 16px 0; margin: 0; color: #cba6f7; }
#toolbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #181825; }
#search  { background: #313244; border: 1px solid #45475a; color: #cdd6f4;
           padding: 4px 8px; border-radius: 4px; font-size: 13px; width: 260px; }
#reset   { background: #6c7086; border: none; color: #cdd6f4; padding: 4px 10px;
           border-radius: 4px; cursor: pointer; }
#reset:hover { background: #7f849c; }
#svg-wrap { overflow-x: auto; padding: 0 16px; }
.frame rect { cursor: pointer; transition: opacity 0.1s; }
.frame rect:hover { opacity: 0.8; }
.frame.dimmed rect { opacity: 0.15; }
#tooltip { position: fixed; background: #313244; border: 1px solid #45475a;
           padding: 8px 12px; border-radius: 6px; font-size: 12px; pointer-events: none;
           display: none; max-width: 400px; line-height: 1.5; z-index: 100; }
#tooltip .fn  { color: #cba6f7; font-weight: bold; }
#tooltip .loc { color: #89dceb; }
#tooltip .pct { color: #a6e3a1; }
.stats { border-collapse: collapse; font-size: 12px; margin: 0 16px; width: calc(100% - 32px); }
.stats th { background: #313244; padding: 4px 8px; text-align: left; color: #89dceb; }
.stats td { padding: 3px 8px; border-bottom: 1px solid #313244; }
.stats tr:hover td { background: #313244; }
.meta { font-size: 11px; color: #6c7086; margin: 4px 16px 16px; }
#breadcrumbs { padding: 4px 16px; font-size: 12px; color: #6c7086; min-height: 22px; }
"""

_JS_TEMPLATE = """
const DATA = __DATA_JSON__;
const totalSamples = __TOTAL_SAMPLES__;

const svg      = document.getElementById("flamegraph");
const tooltip  = document.getElementById("tooltip");
const searchBox = document.getElementById("search");
const resetBtn  = document.getElementById("reset");
const breadcrumbs = document.getElementById("breadcrumbs");

let zoomStack = [];

function showTooltip(e, g) {
  const name  = g.dataset.name;
  const file  = g.dataset.file;
  const line  = g.dataset.line;
  const total = g.dataset.total;
  const self_ = g.dataset.self;
  const pct   = g.dataset.pct;
  const selfPct = (self_ / totalSamples * 100).toFixed(1);
  tooltip.innerHTML =
    `<div class="fn">${esc(name)}</div>` +
    `<div class="loc">${esc(file)}:${line}</div>` +
    `<div class="pct">Total: ${pct}% (${total} samples)</div>` +
    `<div class="pct">Self:  ${selfPct}% (${self_} samples)</div>`;
  tooltip.style.display = "block";
  moveTooltip(e);
}

function moveTooltip(e) {
  tooltip.style.left = Math.min(e.clientX + 12, window.innerWidth - 420) + "px";
  tooltip.style.top  = (e.clientY + 16) + "px";
}

function hideTooltip() { tooltip.style.display = "none"; }

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function applySearch(query) {
  const q = query.toLowerCase();
  document.querySelectorAll(".frame").forEach(g => {
    const match = !q || g.dataset.name.toLowerCase().includes(q)
                     || g.dataset.file.toLowerCase().includes(q);
    g.classList.toggle("dimmed", !match);
  });
}

searchBox.addEventListener("input", () => applySearch(searchBox.value));
resetBtn.addEventListener("click", () => {
  searchBox.value = "";
  applySearch("");
  zoomStack = [];
  breadcrumbs.textContent = "";
  svg.style.transform = "";
});

svg.addEventListener("mousemove", e => {
  const g = e.target.closest(".frame");
  if (g) { showTooltip(e, g); moveTooltip(e); }
});
svg.addEventListener("mouseleave", hideTooltip);
svg.addEventListener("click", e => {
  const g = e.target.closest(".frame");
  if (!g) return;
  zoomStack.push(g.dataset.name);
  breadcrumbs.textContent = "▸ " + zoomStack.join(" ▸ ");
});
"""

_JS_TEMPLATE = _JS_TEMPLATE.replace(
    "const DATA = __DATA_JSON__;", "const DATA = {data_json};"
).replace(
    "const totalSamples = __TOTAL_SAMPLES__;", "const totalSamples = {total_samples};"
)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<h1>{title}</h1>
<div id="toolbar">
  <input id="search" type="text" placeholder="Search functions…" autocomplete="off">
  <button id="reset">Reset</button>
</div>
<div id="breadcrumbs"></div>
<div id="svg-wrap">{svg}</div>
<div id="tooltip"></div>
{stats}
<script>
const DATA = {data_json};
const totalSamples = {total_samples};

const svg      = document.getElementById("flamegraph");
const tooltip  = document.getElementById("tooltip");
const searchBox = document.getElementById("search");
const resetBtn  = document.getElementById("reset");
const breadcrumbs = document.getElementById("breadcrumbs");

let zoomStack = [];

function showTooltip(e, g) {{
  const name  = g.dataset.name;
  const file  = g.dataset.file;
  const line  = g.dataset.line;
  const total = g.dataset.total;
  const self_ = g.dataset.self;
  const pct   = g.dataset.pct;
  const selfPct = (self_ / totalSamples * 100).toFixed(1);
  tooltip.innerHTML =
    '<div class="fn">' + esc(name) + '</div>' +
    '<div class="loc">' + esc(file) + ':' + line + '</div>' +
    '<div class="pct">Total: ' + pct + '% (' + total + ' samples)</div>' +
    '<div class="pct">Self:  ' + selfPct + '% (' + self_ + ' samples)</div>';
  tooltip.style.display = "block";
  moveTooltip(e);
}}

function moveTooltip(e) {{
  tooltip.style.left = Math.min(e.clientX + 12, window.innerWidth - 420) + "px";
  tooltip.style.top  = (e.clientY + 16) + "px";
}}

function hideTooltip() {{ tooltip.style.display = "none"; }}

function esc(s) {{
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

function applySearch(query) {{
  const q = query.toLowerCase();
  document.querySelectorAll(".frame").forEach(g => {{
    const match = !q || g.dataset.name.toLowerCase().includes(q)
                     || g.dataset.file.toLowerCase().includes(q);
    g.classList.toggle("dimmed", !match);
  }});
}}

searchBox.addEventListener("input", () => applySearch(searchBox.value));
resetBtn.addEventListener("click", () => {{
  searchBox.value = "";
  applySearch("");
  zoomStack = [];
  breadcrumbs.textContent = "";
}});

svg.addEventListener("mousemove", e => {{
  const g = e.target.closest(".frame");
  if (g) {{ showTooltip(e, g); moveTooltip(e); }}
}});
svg.addEventListener("mouseleave", hideTooltip);
svg.addEventListener("click", e => {{
  const g = e.target.closest(".frame");
  if (!g) return;
  zoomStack.push(g.dataset.name);
  breadcrumbs.textContent = "\u25b8 " + zoomStack.join(" \u25b8 ");
}});
</script>
</body>
</html>
"""
