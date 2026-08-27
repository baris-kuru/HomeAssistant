"""
Analysis pipeline for DNA methylation data.
  - preprocess_data   : filter CpGs by variance / missing rate
  - run_pca           : PCA on samples
  - run_dmp_analysis  : t-test + BH correction for differentially methylated positions
  - run_enrichment    : Fisher's exact test for genomic region / pathway enrichment
"""

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from scipy import stats


# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess_data(df: pd.DataFrame, var_thresh: float, miss_thresh: float):
    """
    Filter CpGs.

    Parameters
    ----------
    df           : raw beta matrix (CpGs × Samples)
    var_thresh   : minimum inter-sample variance to keep a CpG
    miss_thresh  : maximum fraction of missing values allowed per CpG

    Returns
    -------
    df_filtered  : filtered DataFrame
    n_removed    : number of CpGs removed
    """
    n_before = len(df)

    # 1. Missing-value filter
    miss_rate = df.isnull().mean(axis=1)
    df = df[miss_rate <= miss_thresh]

    # 2. Variance filter
    variances = df.var(axis=1)
    df = df[variances >= var_thresh]

    return df, n_before - len(df)


# ── PCA ───────────────────────────────────────────────────────────────────────

def run_pca(df: pd.DataFrame, n_components: int = 3):
    """
    PCA on samples (rows = samples, cols = CpGs after transposing).

    Returns
    -------
    coords               : ndarray [n_samples × n_components]
    explained_variance   : fraction of variance per PC
    """
    X = df.T.values  # shape: samples × CpGs
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    n_comp = min(n_components, X.shape[0], X.shape[1])
    pca = PCA(n_components=n_comp)
    coords = pca.fit_transform(X_scaled)

    return coords, pca.explained_variance_ratio_


# ── Differential methylation ──────────────────────────────────────────────────

def _bh_correction(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR correction."""
    n = len(p_values)
    order = np.argsort(p_values)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, n + 1)
    adjusted = np.minimum(1.0, p_values * n / ranks)
    # Enforce monotonicity from largest to smallest p
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    return adjusted


def run_dmp_analysis(df: pd.DataFrame, group1_samples: list, group2_samples: list) -> pd.DataFrame:
    """
    Two-sample Welch t-test per CpG, BH-corrected.

    Returns DataFrame with columns:
      CpG, mean_g1, mean_g2, delta_beta, p_value, p_adjusted, neg_log10_p
    """
    rows = []
    for cpg in df.index:
        g1 = df.loc[cpg, group1_samples].values.astype(float)
        g2 = df.loc[cpg, group2_samples].values.astype(float)
        mean1, mean2 = g1.mean(), g2.mean()
        _, p = stats.ttest_ind(g1, g2, equal_var=False)
        rows.append(
            {
                "CpG":         cpg,
                "mean_g1":     mean1,
                "mean_g2":     mean2,
                "delta_beta":  mean2 - mean1,
                "p_value":     p,
            }
        )

    result = pd.DataFrame(rows)
    result["p_adjusted"] = _bh_correction(result["p_value"].values)
    result["neg_log10_p"] = -np.log10(result["p_value"].clip(1e-300))
    return result.sort_values("p_value").reset_index(drop=True)


# ── Enrichment analysis ───────────────────────────────────────────────────────

_PATHWAY_MAP = {
    "Cancer":               ["BRCA1", "TP53", "RB1", "PTEN", "VHL"],
    "DNA Repair":           ["BRCA1", "MLH1", "MGMT"],
    "Cell Cycle":           ["CDKN2A", "RB1", "TP53"],
    "Apoptosis":            ["TP53", "PTEN", "DAPK1"],
    "EMT":                  ["CDH1", "RUNX3", "ESR1"],
    "Wnt Signaling":        ["APC", "RUNX3", "CDH1"],
    "Drug Metabolism":      ["GSTP1", "MGMT"],
    "Tumor Suppression":    ["TP53", "BRCA1", "NF1", "VHL"],
    "Chromatin Remodeling": ["RASSF1", "CDKN2A", "MLH1"],
}


def _fisher_or_ci(a, b, c, d):
    """OR + 95 % CI via Woolf (log) method; fallback-safe."""
    a, b, c, d = max(a, 0.5), max(b, 0.5), max(c, 0.5), max(d, 0.5)
    or_val = (a * d) / (b * c)
    log_or = np.log(or_val)
    se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    ci_lo = np.exp(log_or - 1.96 * se)
    ci_hi = np.exp(log_or + 1.96 * se)
    return float(np.clip(or_val, 0, 50)), float(np.clip(ci_lo, 0, 50)), float(np.clip(ci_hi, 0, 50))


def run_enrichment(
    results_df: pd.DataFrame,
    category: str,
    sig_p: float = 0.05,
    sig_delta: float = 0.15,
) -> pd.DataFrame:
    """
    Fisher's exact test enrichment for each level of a categorical annotation.

    Parameters
    ----------
    results_df : DMP table with columns CpG, delta_beta, p_adjusted, CpG_Context,
                 Gene_Region, Gene
    category   : "cpg_context" | "gene_region" | "pathway"
    """
    is_sig = (results_df["p_adjusted"] < sig_p) & (results_df["delta_beta"].abs() > sig_delta)
    df = results_df.copy()
    df["_sig"] = is_sig

    records = []

    if category == "pathway":
        for pathway, genes in _PATHWAY_MAP.items():
            in_cat = df["Gene"].isin(genes)
            a = int((in_cat & is_sig).sum())
            b = int((in_cat & ~is_sig).sum())
            c = int((~in_cat & is_sig).sum())
            d = int((~in_cat & ~is_sig).sum())
            _, p = stats.fisher_exact([[a, b], [c, d]], alternative="greater")
            or_val, ci_lo, ci_hi = _fisher_or_ci(a, b, c, d)
            records.append(
                {
                    "category":      pathway,
                    "n_total":       int(in_cat.sum()),
                    "n_dmp_in_cat":  a,
                    "odds_ratio":    or_val,
                    "ci_lower":      ci_lo,
                    "ci_upper":      ci_hi,
                    "p_value":       float(p),
                }
            )
    else:
        col = "CpG_Context" if category == "cpg_context" else "Gene_Region"
        for cat_val in df[col].unique():
            in_cat = df[col] == cat_val
            a = int((in_cat & is_sig).sum())
            b = int((in_cat & ~is_sig).sum())
            c = int((~in_cat & is_sig).sum())
            d = int((~in_cat & ~is_sig).sum())
            _, p = stats.fisher_exact([[a, b], [c, d]], alternative="greater")
            or_val, ci_lo, ci_hi = _fisher_or_ci(a, b, c, d)
            records.append(
                {
                    "category":      cat_val,
                    "n_total":       int(in_cat.sum()),
                    "n_dmp_in_cat":  a,
                    "odds_ratio":    or_val,
                    "ci_lower":      ci_lo,
                    "ci_upper":      ci_hi,
                    "p_value":       float(p),
                }
            )

    return pd.DataFrame(records).sort_values("odds_ratio", ascending=False).reset_index(drop=True)
