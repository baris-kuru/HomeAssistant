"""
MethylScope — DNA Methylation Analysis Pipeline
Light theme, single-page scrolling, file upload (CSV / Excel / IDAT info).
"""

import base64, io, warnings
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from mock_data import generate_mock_methylation_data
from analysis import preprocess_data, run_pca, run_dmp_analysis, run_enrichment

warnings.filterwarnings("ignore")

# ── App ───────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
app.title = "MethylScope"
server = app.server

# ── Tokens ────────────────────────────────────────────────────────────────────

BG      = "#F0F4FF"
CARD    = "#FFFFFF"
BORDER  = "#E2E8F0"
P       = "#4F46E5"   # indigo primary
G       = "#10B981"   # green
W       = "#F59E0B"   # amber
R       = "#EF4444"   # red
TEXT    = "#1E293B"
MUTED   = "#64748B"
PLOTBG  = "#F8FAFF"
GC      = ["#4F46E5", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#06B6D4"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _plo(title="", h=400):
    """Base plotly layout kwargs (light theme)."""
    return dict(
        title=dict(text=title, font=dict(size=13, color=TEXT)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PLOTBG,
        font=dict(color=TEXT, size=11, family="system-ui"),
        height=h,
        margin=dict(l=54, r=20, t=44, b=50),
    )


def _card(*children, cls="ms-section mb-4"):
    return html.Div(
        list(children),
        className=cls,
        style={
            "backgroundColor": CARD,
            "borderRadius": "14px",
            "padding": "26px 28px",
            "boxShadow": "0 2px 8px rgba(79,70,229,0.07), 0 1px 2px rgba(0,0,0,0.05)",
            "border": f"1px solid {BORDER}",
        },
    )


def _sh(n, title, color=P):
    """Section header with numbered badge."""
    return html.Div([
        html.Span(str(n), style={
            "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
            "width": "26px", "height": "26px", "borderRadius": "50%",
            "background": color, "color": "#fff",
            "fontSize": "12px", "fontWeight": 700, "marginRight": "10px", "flexShrink": 0,
        }),
        html.Span(title, style={"fontWeight": 700, "fontSize": "15px", "color": TEXT}),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "18px"})


def _pill(val, label, color=P):
    return html.Div([
        html.Div(val,   style={"fontSize": "21px", "fontWeight": 800, "color": color, "lineHeight": 1.2}),
        html.Div(label, style={"fontSize": "11px", "color": MUTED, "marginTop": "2px"}),
    ], style={
        "flex": 1, "minWidth": "110px",
        "background": "#F8FAFF", "borderRadius": "10px",
        "border": f"1px solid {BORDER}", "padding": "13px 16px",
    })


def _pills(*args):
    return html.Div(list(args), style={"display": "flex", "gap": "10px", "marginBottom": "20px",
                                        "flexWrap": "wrap"})


def _tbl(df, conditional=None):
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        style_table={"overflowX": "auto", "borderRadius": "8px", "overflow": "hidden"},
        style_cell={"backgroundColor": "#fff", "color": TEXT, "border": f"1px solid {BORDER}",
                    "padding": "8px 12px", "fontSize": "12px", "textAlign": "center"},
        style_header={"backgroundColor": "#F8FAFF", "fontWeight": 700, "color": TEXT,
                      "border": f"1px solid {BORDER}"},
        style_data_conditional=conditional or [],
        sort_action="native", page_size=12,
    )


# ── Upload parsing ────────────────────────────────────────────────────────────

def _parse(contents, filename):
    """Returns (df | None, error_str | None)."""
    try:
        _, b64 = contents.split(",", 1)
        raw = base64.b64decode(b64)
        ext = filename.lower()

        if ext.endswith(".csv"):
            df = pd.read_csv(io.StringIO(raw.decode("utf-8")), index_col=0)
        elif ext.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw), index_col=0)
        elif ext.endswith(".idat"):
            return None, (
                "IDAT files are raw Illumina BeadChip intensity files and must be "
                "preprocessed before use. They come in Red/Green channel pairs and "
                "require reference manifests.\n\n"
                "Preprocess with methylprep:\n"
                "  pip install methylprep\n"
                "  python -m methylprep process -d /path/to/idat_folder/ -a EPIC\n\n"
                "Then upload the resulting beta_values.csv here."
            )
        else:
            return None, f"Unsupported format '{filename}'. Upload CSV (.csv) or Excel (.xlsx / .xls)."

        df = df.apply(pd.to_numeric, errors="coerce")
        if df.shape[0] < 2 or df.shape[1] < 2:
            return None, "File must have at least 2 rows (CpGs) and 2 columns (samples)."
        return df, None
    except Exception as e:
        return None, f"Could not read file: {e}"


def _infer_meta(columns):
    """Guess group labels from column name patterns."""
    groups = {}
    for col in columns:
        found = None
        for sep in ("_", "-", "."):
            parts = [p for p in col.split(sep) if p and not p.isdigit() and len(p) > 1]
            if parts:
                found = parts[-1]
                break
        groups[col] = found or "Unknown"
    return pd.DataFrame([{"Sample": s, "Group": g} for s, g in groups.items()])


def _mock_anno(index):
    rng = np.random.default_rng(42)
    n = len(index)
    genes = ["BRCA1", "TP53", "MLH1", "CDKN2A", "APC", "MGMT",
             "PTEN", "VHL", "RB1", "NF1", "RASSF1", "CDH1", "DAPK1", "ESR1", "GSTP1", "RUNX3"]
    return pd.DataFrame({
        "CpG_ID":      list(index),
        "Chromosome":  rng.choice([f"chr{i}" for i in range(1, 23)] + ["chrX"], n),
        "Position":    rng.integers(100_000, 250_000_000, n),
        "Gene":        rng.choice(genes, n),
        "CpG_Context": rng.choice(["island", "shore", "shelf", "open_sea"], n, p=[.27, .23, .08, .42]),
        "Gene_Region": rng.choice(["promoter", "exon", "intron", "intergenic"], n, p=[.30, .15, .35, .20]),
    })


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _slabel(txt):
    return html.Div(txt.upper(), style={
        "fontSize": "10px", "fontWeight": 700, "letterSpacing": "1.2px",
        "color": MUTED, "marginBottom": "9px",
    })


sidebar = html.Div([
    # Logo
    html.Div([
        html.Span("🧬", style={"fontSize": "26px"}),
        html.Div([
            html.Div("MethylScope", style={"fontWeight": 800, "fontSize": "16px", "color": P}),
            html.Div("Methylation Pipeline", style={"fontSize": "11px", "color": MUTED}),
        ]),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "28px"}),

    # ── 1. Data ──────────────────────────────────────────────────────────────
    _slabel("1 · Data Source"),
    dcc.Upload(
        id="upload",
        children=html.Div([
            html.Div("⬆", style={"fontSize": "20px", "color": P}),
            html.Div("Click or drag to upload",
                     style={"fontSize": "12px", "fontWeight": 600, "color": TEXT, "marginTop": "3px"}),
            html.Div("CSV · Excel (.xlsx) · IDAT*",
                     style={"fontSize": "10px", "color": MUTED}),
        ], style={"textAlign": "center", "padding": "12px 6px"}),
        style={
            "border": f"2px dashed {P}", "borderRadius": "9px",
            "cursor": "pointer", "background": "#EEF2FF", "marginBottom": "8px",
        },
        multiple=False,
    ),
    html.Div(id="upload-msg", style={"fontSize": "11px", "marginBottom": "8px"}),
    dbc.Button("Use Mock Dataset", id="btn-mock", size="sm", outline=True,
               color="primary", className="w-100 mb-1",
               style={"fontSize": "12px", "fontWeight": 600}),
    html.Div("*IDAT requires methylprep preprocessing",
             style={"fontSize": "10px", "color": MUTED, "marginBottom": "18px",
                    "textAlign": "center"}),

    html.Hr(style={"borderColor": BORDER, "margin": "0 0 16px"}),

    # ── 2. Preprocess ─────────────────────────────────────────────────────────
    _slabel("2 · Preprocess"),
    html.Label("Variance threshold", style={"fontSize": "12px", "color": MUTED}),
    dcc.Slider(id="sl-var", min=0, max=0.02, step=0.001, value=0.002,
               marks={0: "0", 0.01: "0.01", 0.02: "0.02"},
               tooltip={"placement": "bottom", "always_visible": False},
               className="mb-1"),
    html.Label("Max missing rate", style={"fontSize": "12px", "color": MUTED, "marginTop": "6px"}),
    dcc.Slider(id="sl-miss", min=0, max=0.5, step=0.05, value=0.2,
               marks={0: "0%", 0.25: "25%", 0.5: "50%"},
               tooltip={"placement": "bottom", "always_visible": False}),
    dbc.Button("Preprocess & PCA", id="btn-pre", color="success", size="sm",
               className="w-100 mt-3 mb-1", disabled=True,
               style={"fontSize": "12px", "fontWeight": 700}),
    html.Div(id="pre-status", style={"fontSize": "11px", "color": MUTED,
                                      "marginBottom": "16px", "textAlign": "center"}),

    html.Hr(style={"borderColor": BORDER, "margin": "0 0 16px"}),

    # ── 3. DMP ───────────────────────────────────────────────────────────────
    _slabel("3 · Differential Analysis"),
    html.Label("Reference group", style={"fontSize": "12px", "color": MUTED}),
    dcc.Dropdown(id="dd-g1", placeholder="Group 1…", className="mb-2",
                 style={"fontSize": "12px"}),
    html.Label("Comparison group", style={"fontSize": "12px", "color": MUTED}),
    dcc.Dropdown(id="dd-g2", placeholder="Group 2…", style={"fontSize": "12px"}),
    dbc.Button("Run DMP Analysis", id="btn-dmp", color="warning", size="sm",
               className="w-100 mt-3 mb-1", disabled=True,
               style={"fontSize": "12px", "fontWeight": 700, "color": "#000"}),
    html.Div(id="dmp-status", style={"fontSize": "11px", "color": MUTED,
                                      "marginBottom": "16px", "textAlign": "center"}),

    html.Hr(style={"borderColor": BORDER, "margin": "0 0 16px"}),

    # ── 4. Enrichment ─────────────────────────────────────────────────────────
    _slabel("4 · Enrichment"),
    dbc.RadioItems(
        id="radio-enrich",
        options=[
            {"label": "CpG Context", "value": "cpg_context"},
            {"label": "Gene Region",  "value": "gene_region"},
            {"label": "Pathways",     "value": "pathway"},
        ],
        value="cpg_context",
        style={"fontSize": "12px", "color": TEXT},
        className="mb-3",
    ),
    dbc.Button("Run Enrichment", id="btn-enrich", color="danger", size="sm",
               className="w-100", disabled=True,
               style={"fontSize": "12px", "fontWeight": 700}),

], style={
    "width": "244px", "minHeight": "100vh", "flexShrink": 0,
    "padding": "24px 16px", "backgroundColor": "#fff",
    "borderRight": f"1px solid {BORDER}",
    "overflowY": "auto", "position": "sticky", "top": 0, "maxHeight": "100vh",
})


# ── Layout ────────────────────────────────────────────────────────────────────

app.layout = html.Div([
    dcc.Store(id="s-raw"),
    dcc.Store(id="s-meta"),
    dcc.Store(id="s-anno"),
    dcc.Store(id="s-proc"),
    dcc.Store(id="s-dmp"),
    dcc.Store(id="s-enrich"),
    dcc.Store(id="s-g1"),
    dcc.Store(id="s-g2"),
    dcc.Store(id="s-ecat"),

    # Gradient top bar
    html.Div(style={
        "height": "3px",
        "background": f"linear-gradient(90deg, {P} 0%, #818CF8 50%, #06B6D4 100%)",
    }),

    html.Div([
        sidebar,
        html.Div(id="main", style={
            "flex": 1, "padding": "30px 32px", "minWidth": 0,
        }),
    ], style={"display": "flex"}),
], style={"backgroundColor": BG, "minHeight": "100vh", "color": TEXT})


# ── Callbacks: data loading ───────────────────────────────────────────────────

@app.callback(
    Output("s-raw",       "data"),
    Output("s-meta",      "data"),
    Output("s-anno",      "data"),
    Output("btn-pre",     "disabled"),
    Output("dd-g1",       "options"),
    Output("dd-g2",       "options"),
    Output("dd-g1",       "value"),
    Output("dd-g2",       "value"),
    Output("upload-msg",  "children"),
    Input("btn-mock",     "n_clicks"),
    Input("upload",       "contents"),
    State("upload",       "filename"),
    prevent_initial_call=True,
)
def load_data(_, contents, filename):
    ctx = dash.callback_context.triggered[0]["prop_id"]

    if "btn-mock" in ctx or not contents:
        df, anno, meta = generate_mock_methylation_data()
        msg = html.Span(f"✓ Mock data — {len(df):,} CpGs × {len(df.columns)} samples",
                        style={"color": G})
    else:
        df, err = _parse(contents, filename)
        if err:
            return ([dash.no_update] * 8
                    + [html.Span(f"⚠ {err}", style={"color": R, "whiteSpace": "pre-wrap",
                                                     "fontSize": "10px"})])
        meta = _infer_meta(df.columns.tolist())
        anno = _mock_anno(df.index)
        msg  = html.Span(f"✓ {filename} — {len(df):,} CpGs × {len(df.columns)} samples",
                         style={"color": G})

    groups = meta["Group"].unique().tolist()
    opts   = [{"label": g, "value": g} for g in groups]
    g1, g2 = groups[0], (groups[1] if len(groups) > 1 else groups[0])
    return (df.to_json(), meta.to_json(), anno.to_json(),
            False, opts, opts, g1, g2, msg)


@app.callback(
    Output("s-proc",     "data"),
    Output("btn-dmp",    "disabled"),
    Output("pre-status", "children"),
    Input("btn-pre",     "n_clicks"),
    State("s-raw",       "data"),
    State("sl-var",      "value"),
    State("sl-miss",     "value"),
    prevent_initial_call=True,
)
def do_preprocess(_, raw_json, vt, mt):
    df = pd.read_json(raw_json)
    df_f, n_rem = preprocess_data(df, vt, mt)
    status = f"{len(df_f):,} kept · {n_rem:,} removed"
    return df_f.to_json(), False, status


@app.callback(
    Output("s-dmp",      "data"),
    Output("btn-enrich", "disabled"),
    Output("dmp-status", "children"),
    Input("btn-dmp",     "n_clicks"),
    State("s-proc",      "data"),
    State("s-meta",      "data"),
    State("s-anno",      "data"),
    State("dd-g1",       "value"),
    State("dd-g2",       "value"),
    prevent_initial_call=True,
)
def do_dmp(_, proc_json, meta_json, anno_json, g1, g2):
    if not g1 or not g2 or g1 == g2:
        return dash.no_update, True, "Select two different groups."
    df   = pd.read_json(proc_json)
    meta = pd.read_json(meta_json)
    anno = pd.read_json(anno_json)
    s1   = meta[meta["Group"] == g1]["Sample"].tolist()
    s2   = meta[meta["Group"] == g2]["Sample"].tolist()
    res  = run_dmp_analysis(df, s1, s2)
    res  = res.merge(anno[["CpG_ID", "Gene", "CpG_Context", "Gene_Region"]],
                     left_on="CpG", right_on="CpG_ID", how="left")
    is_sig = (res["p_adjusted"] < 0.05) & (res["delta_beta"].abs() > 0.15)
    status = f"{is_sig.sum():,} DMPs found (FDR<5%, |Δβ|>0.15)"
    return res.to_json(), False, status


@app.callback(
    Output("s-enrich",    "data"),
    Output("s-ecat",      "data"),
    Input("btn-enrich",   "n_clicks"),
    State("s-dmp",        "data"),
    State("radio-enrich", "value"),
    prevent_initial_call=True,
)
def do_enrich(_, dmp_json, category):
    if not dmp_json:
        return dash.no_update, dash.no_update
    dmp = pd.read_json(dmp_json)
    return run_enrichment(dmp, category).to_json(), category


# ── Main render ───────────────────────────────────────────────────────────────

@app.callback(
    Output("main", "children"),
    Input("s-raw",    "data"),
    Input("s-proc",   "data"),
    Input("s-dmp",    "data"),
    Input("s-enrich", "data"),
    State("s-meta",   "data"),
    State("sl-var",   "value"),
    State("sl-miss",  "value"),
    State("dd-g1",    "value"),
    State("dd-g2",    "value"),
    State("s-ecat",   "data"),
)
def render(raw_json, proc_json, dmp_json, enrich_json,
           meta_json, vt, mt, g1, g2, ecat):

    # ── Welcome ───────────────────────────────────────────────────────────────
    if not raw_json:
        return _card(
            html.Div([
                html.Div("🧬", style={"fontSize": "52px", "marginBottom": "14px"}),
                html.H2("Welcome to MethylScope",
                        style={"fontWeight": 800, "color": TEXT, "marginBottom": "8px"}),
                html.P("End-to-end DNA methylation analysis — preprocessing, PCA, "
                       "differential methylation, and enrichment.",
                       style={"color": MUTED, "maxWidth": "500px", "margin": "0 auto 28px"}),
                dbc.Row([
                    dbc.Col(_feature_tile("📊", "PCA",       "Visualize sample variance"), width=3),
                    dbc.Col(_feature_tile("🌋", "Volcano",   "Differential methylation"),  width=3),
                    dbc.Col(_feature_tile("🔥", "Heatmap",   "Top DMP patterns"),          width=3),
                    dbc.Col(_feature_tile("📐", "Enrichment","Pathways & regions"),         width=3),
                ], style={"maxWidth": "640px", "margin": "0 auto 24px"}),
                html.Div("← Load data from the sidebar to begin",
                         style={"color": MUTED, "fontSize": "13px"}),
            ], style={"textAlign": "center", "padding": "30px 0"}),
            cls="ms-section",
        )

    sections = []
    df   = pd.read_json(raw_json)
    meta = pd.read_json(meta_json)

    # ── Section 1: Data Overview ──────────────────────────────────────────────
    stat_row = _pills(
        _pill(f"{len(df):,}",             "CpG Sites",   P),
        _pill(f"{len(df.columns)}",       "Samples",     G),
        _pill(f"{df.mean().mean():.3f}",  "Mean β",      W),
        _pill(f"{df.isnull().sum().sum()}", "Missing",   R),
        _pill(f"{meta['Group'].nunique()}", "Groups",    "#8B5CF6"),
    )

    # Violin
    fig_vln = go.Figure()
    for i, col in enumerate(df.columns):
        fig_vln.add_trace(go.Violin(
            y=df[col].values, name=col,
            line_color=GC[i % len(GC)],
            fillcolor=GC[i % len(GC)],
            opacity=0.5, box_visible=True, meanline_visible=True, showlegend=False,
        ))
    fig_vln.update_layout(
        **_plo("β Value Distribution per Sample", 330),
        yaxis=dict(title="β", gridcolor=BORDER, range=[0, 1]),
        xaxis=dict(tickangle=25, gridcolor="rgba(0,0,0,0)"),
    )

    # Group histogram
    fig_hist = go.Figure()
    for i, grp in enumerate(meta["Group"].unique()):
        samps = meta[meta["Group"] == grp]["Sample"].tolist()
        vals  = df[[s for s in samps if s in df.columns]].values.flatten()
        fig_hist.add_trace(go.Histogram(
            x=vals, name=grp, opacity=0.72, nbinsx=50,
            marker_color=GC[i % len(GC)],
        ))
    fig_hist.update_layout(
        **_plo("Pooled β Distribution by Group", 270),
        xaxis=dict(title="β Value", gridcolor=BORDER),
        yaxis=dict(title="CpG count", gridcolor=BORDER),
        barmode="overlay",
        legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=BORDER, borderwidth=1),
    )

    meta_disp = meta.copy()
    sections.append(_card(
        _sh(1, "Data Overview"),
        stat_row,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_vln,  config={"displayModeBar": False}), width=8),
            dbc.Col([
                html.Div("Sample sheet", style={"fontWeight": 600, "fontSize": "12px",
                                                 "color": MUTED, "marginBottom": "8px"}),
                _tbl(meta_disp),
            ], width=4),
        ], className="mb-3"),
        dcc.Graph(figure=fig_hist, config={"displayModeBar": False}),
    ))

    # ── Section 2: PCA ────────────────────────────────────────────────────────
    if proc_json:
        df_p  = pd.read_json(proc_json)
        n_kpt = len(df_p)
        n_rem = len(df) - n_kpt

        coords, expl = run_pca(df_p, n_components=min(5, len(df_p.columns)))
        pca_df = (pd.DataFrame(coords, index=df_p.columns,
                               columns=[f"PC{i+1}" for i in range(coords.shape[1])])
                  .reset_index().rename(columns={"index": "Sample"}))
        pca_df = pca_df.merge(meta[["Sample", "Group"]], on="Sample")

        def _pca_plot(a, b):
            fig = go.Figure()
            for i, grp in enumerate(pca_df["Group"].unique()):
                sub = pca_df[pca_df["Group"] == grp]
                fig.add_trace(go.Scatter(
                    x=sub[f"PC{a}"], y=sub[f"PC{b}"],
                    mode="markers+text", name=grp,
                    text=sub["Sample"], textposition="top center",
                    textfont=dict(size=9),
                    marker=dict(size=15, color=GC[i % len(GC)],
                                line=dict(width=2, color="#fff")),
                ))
            ea  = f"{expl[a-1]*100:.1f}%" if len(expl) >= a else ""
            eb  = f"{expl[b-1]*100:.1f}%" if len(expl) >= b else ""
            fig.update_layout(
                **_plo(f"PC{a} vs PC{b}", 370),
                xaxis=dict(title=f"PC{a} ({ea})", gridcolor=BORDER, zeroline=False),
                yaxis=dict(title=f"PC{b} ({eb})", gridcolor=BORDER, zeroline=False),
                legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=BORDER, borderwidth=1),
            )
            return fig

        # Scree
        pcs = [f"PC{i+1}" for i in range(len(expl))]
        fig_scree = go.Figure()
        fig_scree.add_trace(go.Bar(
            x=pcs, y=[v * 100 for v in expl],
            marker_color=P, opacity=0.8, name="Variance %",
            text=[f"{v*100:.1f}%" for v in expl], textposition="outside",
        ))
        cumv = np.cumsum([v * 100 for v in expl])
        fig_scree.add_trace(go.Scatter(
            x=pcs, y=cumv, name="Cumulative", mode="lines+markers",
            line=dict(color=W, width=2), marker=dict(size=6), yaxis="y2",
        ))
        fig_scree.update_layout(
            **_plo("Scree Plot", 280),
            yaxis=dict(title="Variance (%)", gridcolor=BORDER),
            yaxis2=dict(title="Cumulative %", overlaying="y", side="right",
                        range=[0, 110], tickfont=dict(color=W),
                        gridcolor="rgba(0,0,0,0)"),
            bargap=0.3,
            legend=dict(x=0.5, y=1.08, orientation="h", bgcolor="rgba(0,0,0,0)"),
        )

        badge = html.Div(
            [html.Span(f"✓ {n_kpt:,} CpGs retained", style={"color": G, "fontWeight": 700}),
             html.Span(f"  ·  {n_rem:,} removed  ·  var ≥ {vt}  ·  missing ≤ {mt*100:.0f}%",
                       style={"color": MUTED, "fontSize": "12px"})],
            style={"marginBottom": "16px", "fontSize": "13px"},
        )

        pca_plots = dbc.Row([
            dbc.Col(dcc.Graph(figure=_pca_plot(1, 2), config={"displayModeBar": False}), width=6),
            dbc.Col(dcc.Graph(figure=_pca_plot(1, 3) if coords.shape[1] >= 3 else _pca_plot(1, 2),
                              config={"displayModeBar": False}), width=6),
        ], className="mb-3")

        sections.append(_card(
            _sh(2, "PCA — Principal Component Analysis", G),
            badge, pca_plots,
            dcc.Graph(figure=fig_scree, config={"displayModeBar": False}),
        ))

    # ── Section 3: DMP ────────────────────────────────────────────────────────
    if dmp_json:
        res    = pd.read_json(dmp_json)
        is_sig = (res["p_adjusted"] < 0.05) & (res["delta_beta"].abs() > 0.15)
        sig    = res[is_sig]
        n_hyp  = int((sig["delta_beta"] > 0).sum())
        n_hypo = int((sig["delta_beta"] < 0).sum())

        dmp_pills = _pills(
            _pill(f"{len(res):,}",   "CpGs tested",    MUTED),
            _pill(f"{len(sig):,}",   "DMPs",           P),
            _pill(f"{n_hyp}",        "Hypermethylated", R),
            _pill(f"{n_hypo}",       "Hypomethylated",  G),
        )

        ns = res[~is_sig]

        # Volcano
        fig_vol = go.Figure()
        fig_vol.add_trace(go.Scattergl(
            x=ns["delta_beta"], y=ns["neg_log10_p"], mode="markers",
            name="Not significant",
            marker=dict(color="#CBD5E1", size=4, opacity=0.65),
            hovertemplate="<b>%{text}</b><br>Δβ: %{x:.3f}<extra></extra>",
            text=ns["CpG"],
        ))
        fig_vol.add_trace(go.Scattergl(
            x=sig["delta_beta"], y=sig["neg_log10_p"], mode="markers",
            name=f"DMP (n={len(sig)})",
            marker=dict(color=R, size=6, opacity=0.85, line=dict(width=0.5, color="#fff")),
            hovertemplate="<b>%{text}</b><br>Δβ: %{x:.3f}<br>Gene: %{customdata}<extra></extra>",
            text=sig["CpG"],
            customdata=sig.get("Gene", pd.Series([""] * len(sig))),
        ))
        fig_vol.add_hline(y=-np.log10(0.05), line_dash="dot", line_color="#94A3B8",
                          annotation_text="FDR=0.05", annotation_font_size=9)
        fig_vol.add_vline(x= 0.15, line_dash="dot", line_color="#94A3B8")
        fig_vol.add_vline(x=-0.15, line_dash="dot", line_color="#94A3B8")
        fig_vol.update_layout(
            **_plo(f"Volcano: {g2 or '?'} vs {g1 or '?'}", 420),
            xaxis=dict(title="Δβ (Methylation Difference)", gridcolor=BORDER, zeroline=True, zerolinecolor=BORDER),
            yaxis=dict(title="-log₁₀(FDR-adjusted p)", gridcolor=BORDER),
            legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=BORDER, borderwidth=1),
        )

        # Heatmap (top 30)
        top30 = res.nsmallest(30, "p_adjusted")
        fig_heat = go.Figure(go.Heatmap(
            z=top30[["mean_g1", "mean_g2"]].values.T,
            x=top30["CpG"].tolist(),
            y=[g1 or "Ref", g2 or "Comp"],
            colorscale="RdBu_r", zmid=0.5, zmin=0, zmax=1,
            colorbar=dict(title="β", len=0.85,
                          tickfont=dict(color=TEXT), titlefont=dict(color=TEXT)),
            hovertemplate="CpG: %{x}<br>Group: %{y}<br>β: %{z:.3f}<extra></extra>",
        ))
        fig_heat.update_layout(
            **_plo("Top 30 DMPs — Group Mean β", 250),
            xaxis=dict(tickangle=55, tickfont=dict(size=8)),
        )

        # Table
        tdf = res.nsmallest(15, "p_adjusted")[
            ["CpG", "Gene", "CpG_Context", "Gene_Region", "delta_beta", "p_value", "p_adjusted"]
        ].copy()
        tdf["delta_beta"] = tdf["delta_beta"].round(4)
        tdf["p_value"]    = tdf["p_value"].apply(lambda x: f"{x:.2e}")
        tdf["p_adjusted"] = tdf["p_adjusted"].apply(lambda x: f"{x:.4f}")
        tdf.columns = ["CpG", "Gene", "CpG Context", "Gene Region", "Δβ", "p-value", "FDR"]

        sections.append(_card(
            _sh(3, "Differential Methylation Analysis", W),
            dmp_pills,
            dbc.Row([
                dbc.Col(dcc.Graph(figure=fig_vol,  config={"displayModeBar": False}), width=7),
                dbc.Col(dcc.Graph(figure=fig_heat, config={"displayModeBar": False}), width=5),
            ], className="mb-3"),
            html.Div("Top 15 DMPs", style={"fontWeight": 600, "fontSize": "12px",
                                            "color": MUTED, "marginBottom": "8px"}),
            _tbl(tdf, conditional=[
                {"if": {"filter_query": "{Δβ} > 0", "column_id": "Δβ"},
                 "color": R, "fontWeight": 700},
                {"if": {"filter_query": "{Δβ} < 0", "column_id": "Δβ"},
                 "color": G, "fontWeight": 700},
            ]),
        ))

    # ── Section 4: Enrichment ─────────────────────────────────────────────────
    if enrich_json:
        enrich = pd.read_json(enrich_json)
        clabel = {"cpg_context": "CpG Context", "gene_region": "Gene Region",
                  "pathway": "Pathway"}.get(ecat, ecat or "")

        enr = enrich.sort_values("odds_ratio", ascending=True).copy()
        enr["neg_log10_p"] = -np.log10(enr["p_value"].clip(1e-10))
        enr["sig"] = enr["p_value"].apply(lambda p: "p < 0.05" if p < 0.05 else "p ≥ 0.05")
        bar_col = [R if p < 0.05 else "#CBD5E1" for p in enr["p_value"]]

        fig_bar = go.Figure(go.Bar(
            x=enr["odds_ratio"], y=enr["category"], orientation="h",
            marker_color=bar_col,
            error_x=dict(
                type="data",
                array=(enr["ci_upper"] - enr["odds_ratio"]).clip(0).tolist(),
                arrayminus=(enr["odds_ratio"] - enr["ci_lower"]).clip(0).tolist(),
                visible=True, color="#94A3B8",
            ),
            hovertemplate="<b>%{y}</b><br>OR=%{x:.2f}  DMPs=%{customdata}<extra></extra>",
            customdata=enr["n_dmp_in_cat"].tolist(),
        ))
        fig_bar.add_vline(x=1, line_dash="dot", line_color="#94A3B8",
                          annotation_text="OR=1", annotation_font_size=9)
        fig_bar.update_layout(
            **_plo(f"Enrichment — {clabel}", max(280, len(enr) * 46 + 80)),
            xaxis=dict(title="Odds Ratio (95% CI)", gridcolor=BORDER),
            yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        )

        fig_bub = px.scatter(
            enr, x="odds_ratio", y="neg_log10_p",
            size="n_dmp_in_cat", color="sig", text="category",
            size_max=38,
            color_discrete_map={"p < 0.05": R, "p ≥ 0.05": "#CBD5E1"},
            labels={"odds_ratio": "Odds Ratio", "neg_log10_p": "-log₁₀(p)", "sig": ""},
        )
        fig_bub.update_traces(textposition="top center", textfont=dict(size=10, color=TEXT))
        fig_bub.add_vline(x=1, line_dash="dot", line_color="#94A3B8")
        fig_bub.update_layout(
            **_plo(f"Bubble Plot — {clabel}", 360),
            xaxis=dict(title="Odds Ratio", gridcolor=BORDER, zeroline=False),
            yaxis=dict(title="-log₁₀(p)", gridcolor=BORDER),
            legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=BORDER, borderwidth=1),
        )

        etdf = enrich[["category", "n_total", "n_dmp_in_cat", "odds_ratio", "p_value"]].copy()
        etdf["odds_ratio"] = etdf["odds_ratio"].round(3)
        etdf["p_value"]    = etdf["p_value"].apply(lambda x: f"{x:.4f}")
        etdf.columns       = [clabel, "Total CpGs", "DMPs in Category", "Odds Ratio", "p-value"]

        sections.append(_card(
            _sh(4, "Enrichment Analysis", R),
            dbc.Row([
                dbc.Col(dcc.Graph(figure=fig_bar, config={"displayModeBar": False}), width=5),
                dbc.Col(dcc.Graph(figure=fig_bub, config={"displayModeBar": False}), width=7),
            ], className="mb-3"),
            html.Div(f"{clabel} Enrichment Table",
                     style={"fontWeight": 600, "fontSize": "12px", "color": MUTED, "marginBottom": "8px"}),
            _tbl(etdf),
        ))

    return html.Div(sections)


# ── Feature tile (welcome screen) ─────────────────────────────────────────────

def _feature_tile(icon, title, sub):
    return html.Div([
        html.Div(icon, style={"fontSize": "26px"}),
        html.Div(title, style={"fontWeight": 700, "fontSize": "13px", "marginTop": "6px"}),
        html.Div(sub,  style={"fontSize": "11px", "color": MUTED}),
    ], style={"textAlign": "center", "padding": "16px 8px",
              "background": "#F8FAFF", "borderRadius": "10px", "border": f"1px solid {BORDER}"})


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
