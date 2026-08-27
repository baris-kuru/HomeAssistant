"""
Mock DNA methylation dataset generator.
Produces a realistic beta-value matrix (CpGs × Samples) with
group-specific differential methylation enriched in CpG islands / promoters.
"""

import numpy as np
import pandas as pd


def generate_mock_methylation_data(n_cpgs: int = 1200, seed: int = 42):
    """
    Returns
    -------
    df         : DataFrame [n_cpgs × n_samples], beta values 0–1
    annotation : DataFrame with CpG genomic context
    metadata   : DataFrame with sample group info
    """
    rng = np.random.default_rng(seed)

    # ── Samples ──────────────────────────────────────────────────────────────
    sample_names = (
        [f"Control_{i+1}" for i in range(3)]
        + [f"Case_A_{i+1}" for i in range(3)]
        + [f"Case_B_{i+1}" for i in range(3)]
    )
    groups = ["Control"] * 3 + ["Case_A"] * 3 + ["Case_B"] * 3
    n_samples = len(sample_names)

    # ── CpG annotation ───────────────────────────────────────────────────────
    cpg_ids = [f"cg{str(i + 1_000_000):>08}" for i in range(n_cpgs)]

    chr_labels = [f"chr{i}" for i in range(1, 23)] + ["chrX"]
    chr_weights = np.array([8, 7, 7, 6, 6, 6, 5, 5, 5, 5, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 3, 2])
    chromosomes = rng.choice(chr_labels, n_cpgs, p=chr_weights / chr_weights.sum())
    positions = rng.integers(100_000, 250_000_000, n_cpgs)

    cpg_context_opts = ["island", "shore", "shelf", "open_sea"]
    cpg_context_p    = [0.27,    0.23,   0.08,    0.42]
    cpg_contexts = rng.choice(cpg_context_opts, n_cpgs, p=cpg_context_p)

    gene_region_opts = ["promoter", "exon", "intron", "intergenic"]
    gene_region_p    = [0.30,       0.15,   0.35,     0.20]
    gene_regions = rng.choice(gene_region_opts, n_cpgs, p=gene_region_p)

    cancer_genes = [
        "BRCA1", "TP53", "MLH1", "CDKN2A", "APC", "MGMT",
        "PTEN", "VHL", "RB1", "NF1", "RASSF1", "CDH1",
        "DAPK1", "ESR1", "GSTP1", "RUNX3",
    ]
    gene_names = rng.choice(cancer_genes, n_cpgs)

    # ── Base beta values (context-aware) ─────────────────────────────────────
    beta = np.zeros((n_cpgs, n_samples))
    for i in range(n_cpgs):
        ctx = cpg_contexts[i]
        if ctx == "island":
            base = rng.beta(1, 6)          # mostly unmethylated
        elif ctx in ("shore", "shelf"):
            base = rng.beta(2, 2)          # variable
        else:
            base = rng.beta(5, 2)          # mostly methylated
        beta[i] = np.clip(base + rng.normal(0, 0.04, n_samples), 0, 1)

    # ── Differential methylation (~20 % of CpGs) ────────────────────────────
    n_diff = int(n_cpgs * 0.20)

    # Bias DMP selection toward islands + promoters (realistic cancer pattern)
    dm_weight = np.ones(n_cpgs)
    dm_weight[cpg_contexts == "island"]      *= 2.5
    dm_weight[gene_regions == "promoter"]    *= 2.0
    dm_weight /= dm_weight.sum()

    diff_idx = rng.choice(n_cpgs, n_diff, replace=False, p=dm_weight)

    for idx in diff_idx:
        effect = rng.choice([-0.35, -0.30, -0.25, 0.25, 0.30, 0.35])
        # Case_A: full effect (samples 3–5)
        beta[idx, 3:6] = np.clip(beta[idx, 3:6] + effect + rng.normal(0, 0.03, 3), 0, 1)
        # Case_B: partial effect (samples 6–8)
        beta[idx, 6:9] = np.clip(beta[idx, 6:9] + effect * 0.55 + rng.normal(0, 0.04, 3), 0, 1)

    # ── Build DataFrames ─────────────────────────────────────────────────────
    df = pd.DataFrame(beta, index=cpg_ids, columns=sample_names)

    annotation = pd.DataFrame(
        {
            "CpG_ID":       cpg_ids,
            "Chromosome":   chromosomes,
            "Position":     positions,
            "Gene":         gene_names,
            "CpG_Context":  cpg_contexts,
            "Gene_Region":  gene_regions,
        }
    )

    metadata = pd.DataFrame(
        {
            "Sample": sample_names,
            "Group":  groups,
            "Age":    rng.integers(30, 72, n_samples),
            "Gender": rng.choice(["M", "F"], n_samples),
        }
    )

    return df, annotation, metadata
