# biotech-pipeline-mc

## Summary

How many Phase 2 drugs does a company need for an 80% chance of at least one FDA approval? This Monte Carlo
model answers it from public data only: ClinicalTrials.gov trial durations, FDA review goals, published
phase success rates (BIO 2011–2020; Wong et al. 2019) and HHS ASPE per-trial cost estimates.

- **The success-rate source matters most for the odds of approval.** One Phase 2 asset is eventually
  approved with probability 15.1% (BIO) or 34.4% (Wong); reaching 80% takes 10 assets with BIO rates
  and 4 with Wong rates.
- **More assets reduce the risk of getting nothing, not the cost per approval.** With 5 assets, P(zero
  approvals) is 44.0% (BIO) or 12.2% (Wong). Expected trial cost per approved drug is about $126M (BIO)
  or $73M (Wong) at any portfolio size.
- **Time changes the picture.** Within 5 years, 10 assets under BIO rates give at best 62.7% (no gaps
  between phases) and 48.7% with 6-month gaps.

Probabilities and costs above are closed-form values; the simulation is checked against them in the test
suite. The within-5-years figures depend on trial durations, have no closed form, and are simulated
(200,000 portfolios). Assets are treated as independent, and costs cover direct Phase 2/3 trial costs
only (one trial per phase, 2004–2012 nominal US$), so they are not comparable with total R&D cost
estimates that include failures and capital costs. Illustrative model, not investment or clinical advice.

Figures: [docs/figures/](docs/figures/). License: [MIT](LICENSE) for the code.

> 狀態:資料盤點完成;**模型第三階段**(關卡 + 時程 + 臨床試驗直接花費與風險報告)已實作並通過測試;第四階段圖表已輸出。

## 研究問題

一家持有 N 個二期臨床藥物的生技公司,至少一個獲批的機率是多少?
要燒多少錢、多久?在兩套公開的成功率來源(BIO 2011–2020 與
Wong et al. 2019)下,結論是否一致?

## 範圍

- 起點為二期藥物。BIO 情境的關卡為二期→三期→送件→核准;
  Wong 情境為二期→三期→核准(兩關)。
- 每個關卡為一次機率抽樣,失敗即終止。
- 各階段時程由 ClinicalTrials.gov 的已完成業界試驗重抽。
- 各階段花費採用 HHS ASPE 報告的每個試驗平均成本(固定值,不做隨機抽樣),
  以 2004–2012 年名目美元計;花費的變異來自每個藥物走到哪一關。
  低/高成本領域與三個成本倍率列為敏感度。

## 限制

- 假設各藥物彼此獨立。共用平台技術的藥物可能同時失敗,
  本模型會因此低估風險。
- 成功率來自學術與行業來源,不是政府數據。
- 時程只來自已完成的試驗。尚未完成的長期試驗缺席可能使時程偏短
  (2020 年後開始的試驗最明顯)。納入已終止試驗後,中位數上升約
  0.7–0.8 個月(二期 17.2→17.9、三期 20.1→20.9),列為敏感度。
- 本專案為學習用途,不構成投資或臨床建議。

## 2. 資料來源

| 來源 | 內容 | 本地檔案 | 取得日期 |
|---|---|---|---|
| ClinicalTrials.gov API v2 (`/api/v2/studies`) | Phase 2/3 試驗:階段、狀態、開始日期、主要完成日期、試驗類型、主要贊助者類別 | `data/raw/ctgov_phase2_3_20261028T000018Z.jsonl.gz` + `.manifest.json` | 2026-10-28 00:00 UTC(API data timestamp 2026-10-27T09:00:04) |
| BIO / Informa / QLS, *Clinical Development Success Rates and Contributing Factors 2011–2020* (Feb 2021) | 各階段轉移成功率(Fig. 2, p.7)、LOA(Fig. 5b, p.11) | `data/sources/bio_2011_2020.pdf` | 2026-10-27 |
| Wong, Siah & Lo (2019), *Biostatistics* 20(2):273–286, doi:10.1093/biostatistics/kxx069 | 各階段 POS,依治療領域(Table 2) | `data/sources/wong2019_epmc.xml`(Europe PMC 全文 XML) | 2026-10-27 |

**版權:資料與文獻的版權屬於各自的來源**(ClinicalTrials.gov、BIO / Informa / QLS、Wong et al. 與 Oxford University Press、FDA、HHS ASPE)。本 repo 只包含程式、假設表(`data/assumptions.csv`)與衍生的彙總結果(`data/processed/`、`docs/`);程式碼以 [MIT](LICENSE) 授權。上表「本地檔案」欄中 `data/sources/` 的文件**不在 repo 內**,每份文件的完整標題、作者、年份、下載網址,以及它支撐 assumptions.csv 的哪些列,見 [data/sources/README.md](data/sources/README.md)。

`data/raw/` 已列入 `.gitignore`,不進版控。快照可以用 `scripts/fetch_ctgov.py` 重新抓取,但 CT.gov 資料會持續更新,所以每份 manifest 都記錄了 API data timestamp。
`data/raw/` 裡另有一份較早的快照 `ctgov_phase2_3_20261027`,它沒有試驗類型與贊助者欄位,`clean_durations.py` 不會使用它。

### ClinicalTrials.gov 快照概況

- 查詢:`filter.advanced=AREA[Phase](PHASE2 OR PHASE3)`,共 **133,219** 筆(完整,134 頁)。
- 階段分佈:PHASE2 65,948;PHASE3 42,470;PHASE1+PHASE2 17,165;PHASE2+PHASE3 7,636。
- 主要贊助者類別:INDUSTRY 54,345;OTHER 68,574;其他 10,300。

### 試驗時程(月)

由 `scripts/clean_durations.py` 產生。篩選步驟、剩餘筆數與異常值處理見 [docs/filter_log.md](docs/filter_log.md)。

共同篩選條件:業界主要贊助、介入型、已完成、單一階段試驗。日期規則有四種,**主情境為規則 d**(DECIDED),其餘為敏感度:

| 規則 | 定義 |
|---|---|
| a | 日期未標註類型者視為實際值(ESTIMATED 仍排除) |
| b | 開始與主要完成日期皆標為 ACTUAL(嚴格) |
| c | 規則 a,且開始年份為 2011–2020 |
| d | 規則 a,且開始年份為 2010–2019 |

| 規則 | 階段 | n | 中位數 | P25 | P75 |
|---|---|---|---|---|---|
| a | Phase 2 | 13,616 | 17.0 | 9.9 | 28.4 |
| a | Phase 3 | 14,892 | 19.8 | 11.6 | 32.0 |
| b | Phase 2 | 6,743 | 18.5 | 10.9 | 30.6 |
| b | Phase 3 | 7,074 | 21.6 | 12.6 | 35.3 |
| c | Phase 2 | 6,286 | 17.6 | 10.0 | 29.5 |
| c | Phase 3 | 6,777 | 20.7 | 12.0 | 33.9 |
| d | Phase 2 | 6,479 | 17.2 | 10.0 | 29.0 |
| d | Phase 3 | 7,051 | 20.1 | 12.0 | 33.7 |

異常值處理:時程 ≤ 0、< 1 個月、或 > 180 個月(15 年)的試驗直接排除,不做 winsorize,被排除的列存於 `data/processed/durations_excluded.csv`。< 1 個月規則對中位數的影響在 0.03–0.30 個月之間。
合併階段試驗(敏感度)、納入終止試驗的敏感度、依開始年代分段的結果,以及各步驟筆數,見 filter_log.md。

可重抽的時程向量(欄位:`phase, duration_months, nct_id, start_year`,僅已完成試驗):
`data/processed/durations_main.csv` 為規則 d(主情境);`durations_rule_a.csv`(全部年份)、`durations_rule_b.csv`、`durations_rule_c.csv` 供敏感度使用。

### 成功率摘要(完整資料見 `data/assumptions.csv`)

| 轉移 | BIO 2011–2020(p.7) | Wong 2019 Table 2, all indications |
|---|---|---|
| Phase 1 → 2 | 52.0% (n=4,414) | 66.4% |
| Phase 2 → 3 | 28.9% (n=4,933) | 58.3% |
| Phase 3 → NDA/BLA | 57.8% (n=1,928) | — |
| NDA/BLA → 核准 | 90.6% (n=1,453) | — |
| Phase 3 → 核准 | 52.4%(LOA, p.11) | 59.0% |
| Phase 1 → 核准 | 7.9%(LOA, p.11) | 13.8% |

### `data/assumptions.csv` 的 `status` 欄

| 值 | 意義 |
|---|---|
| `SOURCED` | 數值直接取自來源檔(成功率由程式解析;ASPE 成本依頁碼轉錄)。成本列另有 `role` 欄:`base` 為基準值,`sensitivity` 只用於敏感度 |
| `DECIDED` | 沒有官方數據,但已作出專案決定,理由寫在 `rationale` 欄 |
| `ASSUMPTION` | 沒有官方數據,也尚未決定;數值留空(例外:`gap_months`、`review_extra_months` 依專案指示記預設值 0) |
| `DO_NOT_USE` | 來源數值有疑點,在對照期刊 PDF 之前不得使用 |
| `CANDIDATE` | 已查證出處的候選數值,尚未採用;模型不會讀取 |

`page_verified=no` 代表頁碼尚未對照期刊 PDF 確認(見限制)。

## 3. 假設

**已決定(DECIDED)**,理由見 `assumptions.csv` 的 `rationale` 欄:

- 成功率:BIO 2011–2020 為主情境,Wong 2019 為敏感度情境,同一次模擬不混用。
- 時程主樣本採用規則 d(已完成、未標註日期視為實際值、開始年份 2010–2019)。理由:中位數介於規則 a 與 b 之間;2005–2019 無年代趨勢;排除 2020 年後以避開右側截斷。規則 a/b/c 與「完成+終止」保留為敏感度。
- 審查時間:優先審查 8 個月、標準審查 12 個月(FDA PDUFA VII,NME/原始 BLA,自送件起算),以機率 p_priority 抽取。Wong 的三期→核准關卡時程 = 三期時程 + 審查時程。
- 失敗的藥物,累計時間算到失敗那一關結束。
- 階段成本:基準值為 ASPE 2014 Table 2 的加權平均(二期 13.35、三期 19.89 百萬美元,每個試驗,SOURCED,`role=base`);Table 1 治療領域的最小/最大值只作敏感度(`role=sensitivity`)。進入一個階段就付該階段的成本,不論成功或失敗:二期必付,三期只在通過二期後才付。總花費 = trials_per_phase × overhead_multiplier × cpi_factor × 各階段成本之和。
- **成本不做隨機抽樣。** ASPE 未公布試驗層級的變異(Table 2 的 SD 是各治療領域平均成本之間的差異),沒有有出處的分佈可抽。花費的變異來自「每個藥物走到哪一關」。
- 送件與審查階段的費用不計入(見限制)。
- Wong 情境不拆分 Phase 3 → 核准,只用兩關(P2_P3、P3_APP)。
- 只保留業界主要贊助(lead sponsor class = INDUSTRY)的試驗,與 BIO/Wong 的產業範圍一致。
- 日期只有 `YYYY-MM` 時,以當月 15 日補值。
- Phase 1/2 與 Phase 2/3 合併試驗不納入主樣本,另存一份供敏感度分析。
- 時程 ≤ 0、< 1 個月、或 > 15 年的試驗排除。
- Phase 2/3 時程以試驗時程(開始 → 主要完成)作為代理。

**仍為 ASSUMPTION**:

- **ASSUMPTION** — 試驗與藥物計畫之間的對應方式;以試驗時程代理階段時程。
- **ASSUMPTION** — 優先審查比例 p_priority:未填數值,模型以參數傳入。**敏感度範圍:0 / 0.5 / 1。** 參考資料(不是模型輸入):FDA CDER *New Drug Therapy Approvals 2023*,印刷頁 p.11,55 個新藥中 31 個為優先審查(56%)。若引用此數字有兩個偏誤:(1) 它是**核准藥物**中的比例,不是送件中的比例,被拒的申請不在分母;(2) 只含 CDER,**不含 CBER** 審查的生物製劑。各年的 Novel Drug Approvals 網頁清單沒有優先審查欄位。
- **ASSUMPTION** — 模型**未包含**退回(complete response)與重新送件的循環,每次送件只有一段審查期。
- **ASSUMPTION** — `gap_months`(`ASSUMPTION_GAP_MONTHS`):階段之間的空檔,預設 0。路徑上加兩次:二期結束→三期開始、三期結束→送件。**敏感度範圍:0 / 3 / 6 個月。**
- **ASSUMPTION** — `review_extra_months`(`ASSUMPTION_REVIEW_EXTRA_MONTHS`):每次審查在 PDUFA 目標之外的額外時間,預設 0;尚未設定敏感度範圍。
- **ASSUMPTION** — `trials_per_phase`:每階段的試驗數,預設 1;**敏感度:1、2**。
- **ASSUMPTION** — `cpi_factor`:物價調整係數,預設 1.0(即不調整,結果為 2004–2012 混合年份的名目美元)。
- **ASSUMPTION** — `overhead_multiplier`:ASPE 試驗成本以外的贊助者成本,預設 1.0;**敏感度:1.5、2.0**。
- **敏感度說明:三個成本倍率在公式中只以乘積出現**(總花費 = trials_per_phase × overhead_multiplier × cpi_factor × 各階段成本之和),所以 `trials_per_phase = 2` 與 `overhead_multiplier = 2` 的結果完全相同。`trials_per_phase` 目前同時放大二期與三期;若要表示「只有某一階段跑兩個試驗」,公式需另行調整。
- **ASSUMPTION** — 各階段結果彼此獨立,pipeline 中的各計畫也彼此獨立。
- **ASSUMPTION** — 歷史成功率適用於未來。

## 4. 限制(資料與方法細節)

### 成功率來源

- 成功率來自兩份產業層級的歷史研究,不是本專案從 CT.gov 自行估計的結果。CT.gov 只登錄試驗,沒有「計畫是否進入下一階段」的紀錄,所以不能直接算出轉移機率。
- **BIO 2011–2020**:Biomedtracker 資料,phase-by-phase 方法(進入下一階段數 ÷ 進入或中止總數),有獨立的 NDA/BLA → 核准階段,期間與 CT.gov 樣本較接近。
- **Wong 2019**:Citeline 資料(2000–2015),path-by-path 方法,沒有獨立的 NDA 階段,有提供標準誤。它的 Phase 2 → 3 為 58.3%,BIO 為 28.9%,差距主要來自方法與期間不同。
- **兩者不能在同一次模擬中混用。** BIO 為主情境,Wong 為敏感度情境(ASSUMPTION_SUCCESS_RATE_SOURCE,已決定)。
- 兩份來源都是全產業平均,不反映個別公司、個別適應症或特定藥物類型的差異。
- BIO 報告的 Phase 1 成功率可能因失敗計畫較少公開而偏高(報告 p.6 有說明)。

### 獨立性假設

- 模擬將把每個階段轉移視為獨立的 Bernoulli 事件:進入某階段後的成功機率只取決於該階段,不受前面各階段表現的影響。實際上,前期資料較強的計畫,後期成功率可能較高。
- pipeline 中的各計畫也將被視為彼此獨立。若多個計畫共用同一標的、平台技術或作用機轉,失敗可能高度相關,獨立假設會**低估**「全部失敗」的機率,使價值分佈的尾部風險偏窄。
- 時程與成功與否也將被視為獨立。實際上,終止試驗的時程與完成試驗不同(本資料中終止試驗較長),而本專案的時程樣本只納入已完成的試驗。

### 資料

- **Wong 2019 的頁碼未驗證。** OUP 與 PMC 的 PDF 下載被擋(403 / bot 檢查),數值只能從 Europe PMC XML 取得,所以頁碼只標文章範圍 273–286 並標記 `page_verified=no`。
- **Wong Table 2 的 "All without oncology" 列標為 `DO_NOT_USE`。** 在 all-indications 與 lead-indications 兩個區塊中,該列的 POS(2→3) 都等於 POS(2→APP)(27.3/27.3、29.0/29.0),疑似排版錯誤。另外 "Overall" 列的 SE 與 n 不一致,已在 `notes` 欄標記。
- **嚴格規則(b)的時程樣本偏向近年。** 較舊的 CT.gov 紀錄常沒有日期類型標記,規則 b 會把它們排除:2000 年代的完成試驗只保留 12%,規則 a 保留 85%(見 filter_log.md)。
- **規則 a 有一半以上的試驗至少一個日期只有年月**(規則 b 為 6%),以 15 日補值會增加約 ±0.5 個月的誤差。
- **試驗時程不等於階段時程。** 同一階段可能有多個平行或接續的試驗,試驗之間也可能有空檔。
- 只納入「已完成」試驗:尚未完成的長期試驗不在內,會使時程偏短,近年起始的試驗尤其明顯。至於終止試驗,資料顯示它們從開始到主要完成日(即停止日)的中位數反而比已完成試驗**長** 0.8–4.8 個月(見 filter_log.md 的 TERMINATED 敏感度),納入後整體中位數只增加 0.0–0.8 個月。因此在本資料中,排除終止試驗並沒有使時程偏長。
- 模型中失敗的藥物也使用已完成試驗的時程。若失敗路徑的時程有偏差,方向是偏短:終止試驗(失敗的代理)的時程比已完成試驗長。
- **基準情境的階段空檔為 0,時程偏短。** 實際上二期結束到三期開始、三期結束到送件之間通常有空檔;`gap_months` 的敏感度(0 / 3 / 6)見 docs/timed_results.md。
- **模型不含退回重送。** 但 BIO 的送件→核准 90.6% 包含重送後才核准的案例:這些藥物在模型中只有一段審查期,核准時間被低估。

### 臨床試驗直接花費

- **ASPE 成本是「一個試驗」的成本**,不是整個計畫,也沒有分攤失敗計畫的花費(印刷頁 3-2)。本模型的失敗由關卡模擬處理:失敗藥物仍付它進入過的階段的成本。
- **送件與審查階段的費用不計入。** ASPE 的送件欄只是 PDUFA 申請費(`ASPE14_COST_NDA_FEE`,CANDIDATE,僅供參考);贊助者準備送件的成本沒有出處。
- **幣值為名目美元、年份混合**(2004–2012 的合約資料,未經通膨調整);`cpi_factor` 預設 1.0,所以結果沒有換算成任何單一年份的幣值。未折現。
- **成本為預算值**:議定合約單價 × 計畫收案人數與試驗場所數,不是實際支出;報告未說明提早停止的試驗是否在樣本中。
- **只含美國試驗**的成本。
- VaR 與 CVaR 在本模型中資訊有限:成本固定,N 個藥物的總花費只有 N+1 種可能值,上限為 N × (二期 + 三期成本);N 小時 VaR 等於 CVaR。主要風險指標為 P(零核准) 與零核准時的花費。
- 本模型只計二期與三期各一個試驗的直接花費,不含一期、臨床前、資本成本與現值,且為 2004–2012 年名目美元,不可與文獻中含失敗與資本成本的總研發成本估計直接比較。
- ASPE Table 2 的 SD 是治療領域之間的差異,不能當作單一試驗成本的不確定性;Table 1 的最小/最大值敏感度中,二期與三期的極值來自不同領域。
- BIO p.11 "Gastroenterology\*" 的註腳文字在 PDF 文字層中找不到。
- **Wong 兩關連乘與原文不一致。** 0.583 × 0.590 = 34.4%,但 Wong Table 2 印出的 Phase 2 → 核准為 35.1%(path-by-path 方法下,各關 POS 的乘積不一定等於整段 POS)。模型維持原數字、照範圍定義使用兩關連乘,結果為 34.4%,不調整為 35.1%。BIO 三關連乘 15.13%,與其 LOA 15.1% 一致。

## 模型

`src/biotech_pipeline_mc/`:

- `params.py`:`load_gate_probs(scenario)` 依 `param_id` 從 `data/assumptions.csv` 讀取成功率,只接受 `status=SOURCED` 的列。
  - BIO:`BIO21_POS_P2_P3_ALL_INDICATIONS`、`BIO21_POS_P3_NDA_ALL_INDICATIONS`、`BIO21_POS_NDA_APP_ALL_INDICATIONS`
  - Wong:`WONG19_ALL_P2_P3_OVERALL`、`WONG19_ALL_P3_APP_OVERALL`
- `gates.py`:`simulate_asset(gate_probs, n, rng)` 每關做一次伯努利抽樣,失敗即停,回傳 `stopped_at`(失敗的關卡索引,核准則為關卡數)與 `approved`。固定種子 `DEFAULT_SEED`,使用 `numpy.random.Generator`。

模擬值與解析值的對照表見 [docs/gate_validation.md](docs/gate_validation.md)。

第二階段(時程):

- `params.py`:`load_duration_vectors()` 讀取 `durations_main.csv`;`load_review_months()` 依 `param_id` 讀取 `FDA_PDUFA_PRIORITY_NME`、`FDA_PDUFA_STANDARD_NME`(只接受 SOURCED/DECIDED)。
- `timing.py`:二期、三期時程各從向量重抽一個;審查時間以 `p_priority`(必填參數,無預設值)在 8 與 12 個月間抽。關卡時程:BIO 為 二期 / 空檔 + 三期 / 空檔 + 審查 + 額外審查時間;Wong 為 二期 / 空檔 + 三期 + 空檔 + 審查 + 額外審查時間(`gap_months`、`review_extra_months` 預設 0)。`simulate_asset_timed` 回傳每個藥物停在哪一關、是否核准、累計時間(算到停止的那一關結束);`simulate_portfolio_timed` 模擬 N 個藥物同時起跑,回傳核准數與第一個核准的時間。
- 結果(BIO 與 Wong 並排;p_priority = 0 / 0.5 / 1 × gap_months = 0 / 3 / 6;P(至少一個在 5 / 7 / 10 年內核准)、P(零核准)、第一個核准時間)見 [docs/timed_results.md](docs/timed_results.md)。

第三階段(臨床試驗直接花費與風險報告):

- `params.py`:`load_value(param_id, column, allowed_status)`、`load_sensitivity_values(param_id)`,所有數值與敏感度範圍都從 `assumptions.csv` 以名稱讀取。
- `costs.py`:`analytic_cost_distribution` 給出 N 個藥物總花費的精確離散分佈(含零核准的聯合機率),`discrete_quantile`/`discrete_var_cvar` 由它算分位數與 VaR/CVaR;`load_cost_inputs(cost_case, **overrides)` 讀取階段成本(只接受 SOURCED)與三個乘數;`gate_costs` 給出進入每一關要付的成本(BIO:二期 / 三期 / 0;Wong:二期 / 三期);`asset_costs` 依每個藥物停在哪一關累計花費;`analytic_expected_asset_cost` = 二期成本 + 通過二期機率 × 三期成本;`var_cvar` 計算 VaR95 與 CVaR95(高花費為壞的一端)。程式中沒有寫入任何數值(測試會檢查)。
- `timing.py`:`simulate_portfolio_assets` 回傳每個藥物的結果(形狀 n × N),時程與花費用同一次模擬。
- 結果(N = 1–10,BIO 與 Wong 並排:花費分佈、VaR95/CVaR95、零核准、每個核准藥物的預期花費、5/7/10 年內核准機率、敏感度)見 [docs/cost_results.md](docs/cost_results.md)。

第四階段(圖表,英文,給 LinkedIn 讀者):`scripts/make_figures.py` 只讀取 `data/processed/*.csv` 與 `assumptions.csv`,不重新模擬,輸出至 `docs/figures/`(寬 1600 像素;BIO 固定藍色 #2a78d6、Wong 固定橘色 #eb6834,已通過色盲檢查)。每張圖所用的數字見 [docs/figures/figure_numbers.md](docs/figures/figure_numbers.md)。
- **數字規則:README 與圖表中引用的機率與花費一律使用解析值**(封閉公式或精確離散分佈),模擬值只用於驗證;例外是「X 年內核准」,它取決於時程,沒有封閉解,只能用模擬值。例:BIO 單一藥物核准機率 15.1%、Wong 34.4%;每個核准藥物的預期試驗花費 BIO $126M、Wong $73M(與 N 無關)。解析值與模擬值的並列比較見 figure_numbers.md 與 cost_results.md 第 5 節。
- Fig 1 `fig1_p_approval_by_n.png`:P(至少一個核准) 對 N = 1–10。實線為最終(解析值 1 − (1 − p)^N);虛線為 5 年內(模擬,p_priority = 0.5),虛線是色帶上緣 = 階段空檔 0 個月(樂觀),色帶下緣 = 空檔 6 個月。標出最終達到 80% 所需的 N(BIO 10、Wong 4)。
- Fig 2 `fig2_cost_distribution_n5.png`:N = 5 的臨床試驗直接花費分佈(精確二項機率,離散長條),斜線為零核准的部分。
- Fig 3 `fig3_sensitivity.png`:敏感度排序圖,(i) N = 5 時 5 年內至少一個核准(模擬)、(ii) 每個核准藥物的預期花費(解析值);只畫會改變該指標的因素。10 年內的結果只列在 figure_numbers.md。

## 如何重現

需要 Python 3.9 以上(開發環境為 Python 3.9.6,macOS)。

**1. 建立環境**

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip   # Python 3.9 內建的 pip 21 不支援 pyproject 的 editable 安裝
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e ".[test,figures]" --no-deps
```

`requirements.lock` 由 `pip freeze --exclude-editable` 產生(numpy、pypdf、pytest、matplotlib 與其相依套件的固定版本)。

**2. 執行測試**

```bash
.venv/bin/python -m pytest
```

測試只需要 repo 內的檔案(`data/assumptions.csv`、`data/processed/durations_main.csv`),不需要下載任何資料。

**3. 重跑模型與圖表**(使用 repo 內的假設表與時程,依序執行)

```bash
.venv/bin/python scripts/validate_gates.py      # 關卡:模擬值 vs 解析值 -> docs/gate_validation.md
.venv/bin/python scripts/run_timed.py --p-priority 0 0.5 1 --gap-months 0 3 6   # 第一個核准時間 -> docs/timed_results.md
.venv/bin/python scripts/run_costs.py           # 臨床試驗直接花費與風險 -> docs/cost_results.md
.venv/bin/python scripts/make_figures.py        # 圖表 -> docs/figures/(讀取 run_costs.py 的輸出)
```

固定種子,所以結果與 repo 內的檔案相同(執行時間戳除外)。

**4.(選用)從原始資料重建輸入**

```bash
.venv/bin/python scripts/fetch_ctgov.py         # 抓取 CT.gov 快照 -> data/raw/(不覆蓋舊檔)
.venv/bin/python scripts/clean_durations.py     # 用最新的完整快照 -> data/processed/durations_*.csv、docs/filter_log.md
# 先依 data/sources/README.md 下載來源文件到 data/sources/
.venv/bin/python scripts/build_assumptions.py   # 從來源文件重建 data/assumptions.csv
```

之後再依序執行第 3 步。CT.gov 資料會持續更新,新快照的時程不會與 repo 內的結果完全相同;每份快照的 manifest 都記錄 API data timestamp。

## 目錄結構

```
LICENSE            MIT(程式碼)
data/raw/          CT.gov 原始快照 + manifest(gitignored)
data/sources/      README.md(文件清單與下載網址);文件本身不在 repo 內(gitignored)
data/processed/    時程向量(durations_main.csv = 規則 d、durations_rule_a/b/c.csv)、含規則旗標的完整列表、
                   被排除的列、各規則摘要、終止試驗敏感度、< 1 個月排除前後比較、年代分段、gate_validation.csv、timed_first_approval.csv、cost_results.csv、cost_approval_within.csv、cost_distribution.csv
data/assumptions.csv
docs/filter_log.md 篩選步驟與筆數(由 clean_durations.py 產生)
docs/gate_validation.md 模擬值 vs 解析值(由 validate_gates.py 產生)
docs/timed_results.md   第一個核准時間(由 run_timed.py 產生)
docs/cost_results.md    臨床試驗直接花費與風險報告(由 run_costs.py 產生)
docs/figures/           三張 PNG 與 figure_numbers.md(由 make_figures.py 產生)
scripts/           fetch_ctgov.py, build_assumptions.py, clean_durations.py, validate_gates.py, run_timed.py, run_costs.py, make_figures.py
src/biotech_pipeline_mc/   params.py, gates.py, timing.py, costs.py
tests/             test_gates.py, test_timing.py, test_costs.py
```
