# Research Document Audit

**Document:** `tests\fixtures\sample_manuscript.md`  
**Profile:** thesis  
**Findings:** 8 total — 1 high, 6 medium, 1 low, 0 info

## Executive summary

- **High:** 1
- **Medium:** 6
- **Low:** 1

## Findings

### 1. [HIGH] In-text citation missing from bibliography

`CIT002` · confidence: high (paragraph 6)

Doe (2021) appears in the text but no matching bibliography entry was found.

Evidence:
- Doe, 2021

**Recommended action:** Add the source to the bibliography or correct the in-text citation.

### 2. [MEDIUM] Objective may not be addressed in findings

`ALG003` · confidence: low (Objectives, paragraph 2)

No finding or conclusion item has strong keyword overlap with this objective.

Evidence:
- Assess staff retention among nurses in Lagos hospitals.
- Closest finding: The analysed sample included 140 participants. The response rate was 80% during data collection. The final response rate was 75%.

**Recommended action:** Confirm that the findings explicitly answer this objective.

### 3. [MEDIUM] Bibliography entry is not cited

`CIT003` · confidence: medium (References, paragraph 13)

Smith (2020) is listed in the bibliography but was not found in the body text.

Evidence:
- Smith, J. (2020). Staff retention in hospitals. Journal of Health Research, 2(1), 1–10.

**Recommended action:** Cite the source in the text or remove it from the bibliography.

### 4. [MEDIUM] Conflicting sample-size candidates

`NUM001` · confidence: medium

The manuscript appears to report 2 different sample sizes.

Evidence:
- n=120 at paragraph(s) 6
- n=140 at paragraph(s) 8

**Recommended action:** Confirm whether these values describe recruited, eligible, analysed, or subgroup samples and label them explicitly.

### 5. [MEDIUM] Conflicting percentage candidates

`NUM002` · confidence: medium

Different values are reported for response rate: 80%, 75%.

Evidence:
- 80% at paragraph(s) 8
- 75% at paragraph(s) 8

**Recommended action:** Confirm whether the percentages use different populations or time points and label the denominator for each.

### 6. [MEDIUM] Missing ethics or consent statement

`REQ_ETHICS` · confidence: medium

No ethics or consent statement was detected under the thesis profile.

**Recommended action:** Add an ethics or consent statement, or disable this rule in an institutional profile when it does not apply.

### 7. [MEDIUM] Table is not mentioned in the text

`VIS001` · confidence: high (paragraph 9)

Table 1 has a caption but no cross-reference elsewhere in the manuscript.

Evidence:
- Table 1 Respondent characteristics

**Recommended action:** Discuss Table 1 in the body text.

### 8. [LOW] Missing AI-use disclosure

`REQ_AI_USE` · confidence: medium

No AI-use disclosure was detected under the thesis profile.

**Recommended action:** Add an AI-use disclosure, or disable this rule in an institutional profile when it does not apply.

## Coverage and limits

- **Citation Bibliography Matching:** automated (author–date styles)
- **Numeric Consistency:** automated heuristic screening
- **Objective Question Finding Alignment:** automated lexical screening
- **Reference Existence And Metadata:** not run (use --online-references)
- **Retraction Status:** not run (use --online-references)
- **Claim To Source Support:** not automated in v0.2; requires reliable source full text
- **Institutional Rules:** default public profile; custom NovaPoint rules are a later private layer

## Document statistics

- **Paragraphs:** 13
- **Words:** 91
- **Headings:** 6
- **Tables:** 0
- **Drawings:** 0
- **Citation Occurrences:** 1
- **Unique Citations:** 1
- **Bibliography Entries:** 1
- **Parsed Bibliography Entries:** 1
- **Bibliography Entries With Doi:** 0

> This report is a screening aid. Low-confidence heuristics require human review, and a source not found during an online check is not automatically fabricated.

