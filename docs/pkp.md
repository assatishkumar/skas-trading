# 📄 PKP Non-Options Strategy: Backtesting Requirements

**Strategy Name:** Paiso Ka Ped (PKP) Non-Options Inspired Strategy
**Objective:** To systematically accumulate an asset and generate income through rule-based profit booking and reinvestment (compounding), subject to specific limitations on tactical buying.
**Trigger Prices:** End-of-Day (EOD) Closing Prices.

---

## 1. ⚙️ Configuration Parameters (Inputs)

These values must be user-configurable before execution.

| ID | Parameter Name | Symbol | Description | Data Type | Default Example |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **P-1** | Asset Ticker | A | The security to trade. | String | Nifty Bees |
| **P-2** | Base SIP Amount | $S_{\text{base}}$ | Minimum systematic investment amount. | Currency | ₹1,000 |
| **P-3** | BID Multiplier | $M$ | Used to calculate the base BID amount: $X = M \times S_{\text{base}}$. | Float | $0.5$ |
| **P-4** | Profit Compounding % | $C$ | Percentage of the $\mathbf{R}$ added to the SIP amount. | Float (0.0 to 1.0) | $0.10$ |
| **P-5** | SIP Frequency | $F_{\text{SIP}}$ | Weekly or Monthly. | String | Monthly (1st Trading Day) |
| **P-6** | Min Profit Booking Amount | $V_{\text{min}}$ | Minimum monetary value to book profit. | Currency | ₹10,000 |
| **P-7** | BID Trigger % Drop | $\Delta D_{\text{Buy}}$ | Base drop percentage from $\mathbf{APP}$ to trigger a buy. | Float | $0.02$ (2%) |

---

## 2. 📊 State Variables (Tracked Data)

| ID | Variable Name | Symbol | Recalculation Trigger |
| :--- | :--- | :--- | :--- |
| **V-1** | Total Units Held | $U_{\text{total}}$ | After every Buy or Sell transaction. |
| **V-2** | **Base Investment Amount** | $\mathbf{BIA}$ | Cumulative cost of all purchases. **Never decreases.** |
| **V-3** | **PKP Avg Price** | $\mathbf{PAP}$ | $\mathbf{BIA} / U_{\text{total}}$. Recalculated after every transaction. |
| **V-4** | Profit Reserve | $\mathbf{R}$ | After every Profit Booking (Sell) and SIP/BID Reinvestment. |
| **V-5** | Current SIP Amount | $\mathbf{S}_{\text{current}}$ | Fixed to $S_{\text{base}}$. |
| **V-6** | **Current BID Stage** | $K_{\text{stage}}$ | Tracks the next allowable BID level (0, 1, 2, 3). Resets to 0 on Sell. |
| **V-7** | **BIDs Executed Count** | $\mathbf{N}_{\text{count}}$ | **After every successful BID transaction (Initial: 0).** |
| **V-8** | **Actual Invested** | $\mathbf{I}_{\text{actual}}$ | Fresh capital infused (Cost - Reserve Used). Formerly "Out of Pocket". |

---

## 3. 🎯 Functional Requirements (REQ-F)

### REQ-F1: Fixed SIP Amount & Reserve Usage

*   **Trigger:** Executed prior to every SIP run ($F_{\text{SIP}}$).
*   **Formula:** $\mathbf{S}_{\text{current}} = S_{\text{base}}$ (Fixed).
*   **Reserve Usage:** Calculate reserve to use: $R_{\text{use}} = \min(\mathbf{S}_{\text{current}}, \mathbf{R} \times C)$.
*   **Action:** Set the $\mathbf{S}_{\text{current}}$ for the upcoming SIP purchase.

### REQ-F2: Systematic Investment Purchase (SIP)

*   **Trigger:** Execute on the day defined by $P_{\text{SIP}}$.
*   **Action:** Purchase units of Asset A equal to the $\mathbf{S}_{\text{current}}$ amount at the EOD Close Price.
*   **Updates:**
    *   Recalculate $\mathbf{APP}$ (V-2) and update $U_{\text{total}}$ (V-1).
    *   Reduce $\mathbf{R}$ by $R_{\text{use}}$.
    *   Increase $\mathbf{I}_{\text{actual}}$ by $(\mathbf{S}_{\text{current}} - R_{\text{use}})$.

### REQ-F3: Tactical Buy-on-Dip (BID) - **Strict Progression (Up to 10x)**

*   **Pre-calculation:** Calculate the Base BID Unit Amount $\mathbf{X} = P_{M} \times S_{\text{base}}$.
*   **Capacity:** There is **NO limit** on the total number of BIDs over the lifetime of the strategy.
*   **Daily Restriction:** Only **ONE** BID transaction is permitted per trading day.
*   **Progression Logic:** BIDs must be executed in strict order: $1\times \rightarrow 2\times \rightarrow \dots \rightarrow 10\times$.
    *   The **Current BID Stage** ($K_{\text{stage}}$) determines the multiplier $M = K_{\text{stage}} + 1$.
    *   Maximum Multiplier is $10\times$.
    *   Once $10\times$ is executed, no further BIDs are allowed until the stage is reset by a **Sell**.

| Stage ($K$) | Multiplier ($M$) | Trigger Condition | Purchase Amount |
| :--- | :--- | :--- | :--- |
| **0** | $1\times$ | $\text{Close Price} \leq \mathbf{PAP} \times (1 - 1 \times \Delta D_{\text{Buy}})$ | $1 \times \mathbf{X}$ |
| **1** | $2\times$ | $\text{Close Price} \leq \mathbf{PAP} \times (1 - 2 \times \Delta D_{\text{Buy}})$ | $2 \times \mathbf{X}$ |
| ... | ... | ... | ... |
| **9** | $10\times$ | $\text{Close Price} \leq \mathbf{PAP} \times (1 - 10 \times \Delta D_{\text{Buy}})$ | $10 \times \mathbf{X}$ |

*   **Action:**
    1.  Check if $K_{\text{stage}} < 10$.
    2.  Check the condition for the next multiplier $M = K_{\text{stage}} + 1$.
    3.  If met, execute the purchase ($M \times \mathbf{X}$).
    4.  **Reserve Usage:** Calculate reserve to use: $R_{\text{use}} = \min(\text{Cost}, \mathbf{R} \times C)$.
    5.  **Increment $K_{\text{stage}}$ by 1.**
*   **Updates:**
    *   Update $\mathbf{BIA}$ (V-2), $U_{\text{total}}$ (V-1).
    *   Recalculate $\mathbf{PAP}$ (V-3).
    *   Reduce $\mathbf{R}$ by $R_{\text{use}}$.
    *   Increase $\mathbf{I}_{\text{actual}}$ by $(\text{Cost} - R_{\text{use}})$.
    *   **Increment $\mathbf{N}_{\text{count}}$ (V-7) by 1.**

### REQ-F4: Profit Harvesting (Sell)

* **Calculations:**
    *   **Total Profit:** $P_{\text{total}} = (\text{Close Price} \times U_{\text{total}}) - \mathbf{BIA}$
    *   **Target Sell Value:** $V_{\text{target}} = \max(V_{\text{min}}, 0.01 \times (\text{Close Price} \times U_{\text{total}}))$
* **Trigger:** Check daily if the Total Profit satisfies the target: $P_{\text{total}} \geq V_{\text{target}}$.
* **Action:** Sell units worth $V_{\text{target}}$ at the EOD Close Price.
    *   $\text{Units to Sell} = \text{int}(V_{\text{target}} / \text{Close Price})$
* **Updates:** Update $U_{\text{total}}$ (V-1). Recalculate $\mathbf{PAP}$ (V-3). Add proceeds to $\mathbf{R}$ (V-4).
* **Reset:** Set **Current BID Stage ($K_{\text{stage}}$) to 0.**

---

## 4. 📝 Non-Functional Requirements (REQ-N)

| ID | Requirement | Description |
| :--- | :--- | :--- |
| **REQ-N1** | Atomicity | All Buy/Sell rules must be checked daily. The SIP (F2) and BID (F3) rules must not execute on the same day. |
| **REQ-N2** | Accuracy | All calculations for units must use floating-point arithmetic. Final traded units must be rounded down to the nearest integer. |
| **REQ-N3** | Data Dependency | Requires historical daily Open, High, Low, Close (OHLC) data for the Asset (P-1). |
| **REQ-N4** | Recalculation Order | The $\mathbf{APP}$ (V-2) must be recalculated immediately after any purchase (F2, F3) and before the next day's evaluation. |