# Research references and source notes

This is a source list for future implementation/evaluation, not a claim that the listed datasets have been downloaded or reviewed experimentally.

- Wang W, den Brinker AC, Stuijk S, de Haan G. Algorithmic Principles of Remote PPG. *IEEE Transactions on Biomedical Engineering*. 2017;64(7):1479–1491. DOI: 10.1109/TBME.2016.2609282. POS method background.
- de Haan G, Jeanne V. Robust pulse rate from chrominance-based rPPG. *IEEE Transactions on Biomedical Engineering*. 2013;60(10):2878–2886. DOI: 10.1109/TBME.2013.2266196. CHROM.
- Verkruysse W, Svaasand LO, Nelson JS. Remote plethysmographic imaging using ambient light. *Optics Express*. 2008;16(26):21434–21445. DOI: 10.1364/OE.16.021434.
- UBFC-rPPG benchmark/toolbox: https://github.com/ubicomplab/rPPG-Toolbox . Verify individual dataset terms and protocol before use.
- COHFACE dataset information: https://www.idiap.ch/en/dataset/cohface . Candidate synchronized pulse/respiration reference source; access and metadata need verification.
- Eyes-defy-anemia dataset landing page: https://ieee-dataport.org/documents/eyes-defy-anemia . Availability, label detail, identifiers, license and augmentation provenance remain unverified in this checkout.
- Eyes-defy-anemia publication: https://pmc.ncbi.nlm.nih.gov/articles/PMC12717107/ . Consult the paper and supplementary methods before any reproduction; no results are reproduced here.
- Original research baseline: https://github.com/mrzamaniiii/Contactless-Vital-Sign-Monitoring-Motion-Aware-rPPG . Existing target code's MIT license and attribution are retained.
- WHO haemoglobin guideline: World Health Organization. *Guideline on haemoglobin cutoffs to define anaemia in individuals and populations*. 2024. https://www.who.int/publications/i/item/9789240088542 . Thresholds are population-category dependent; do not use a universal cutoff.
- PRV vs HRV: pulse-derived intervals and ECG R–R intervals are different measurement modalities; agreement must be evaluated against synchronized ECG, and PRV must not be relabeled as ECG HRV.
