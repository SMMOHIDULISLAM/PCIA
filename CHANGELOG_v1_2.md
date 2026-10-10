# PCIA Proposal Processor v1.2.0

## Rules implemented

1. **Account numbers**
   - Preserves the original written form.
   - Converts segmented full accounts such as `3043-901-7337` to the comparable 13-digit form `3043901007337` by padding the final component.
   - Stores short typed accounts such as `CD-24040`, `SB-123456`, and `STD-12345` separately from full accounts.
   - Flags only differing numbers within the same account style.

2. **Firm and individual separation**
   - Stores the business/firm and proprietor/individual separately.
   - Recognizes `M/s`, `Limited`, `Enterprise`, `Traders`, `Firm`, `Agro`, `Poultry Farm`, and similar business indicators.
   - Marks an uncertain entity type for operator review instead of inventing a firm.

3. **Name spelling**
   - Treats `Mia` and `Miah` as an acceptable comparison variation.
   - Preserves the spelling selected from the strongest source or operator decision.

4. **Interest-rate roles**
   - Separates the general/default rate, branch-recommended rate, and final approved rate.
   - Uses the priority: final approval > branch recommendation > general/default rate.
   - Does not treat different semantic rate roles as an automatic conflict.

5. **NID formats**
   - Retains 10-digit, 13-digit, and 17-digit NIDs separately.
   - Combines them in the resolved output without treating different valid lengths as a conflict.
   - Flags only differing NIDs of the same length or identity-role mismatch.

6. **Extraction explanations**
   - Adds `variation_explanations.json` to each result package.
   - Acceptable variations are explained and excluded from the anomaly count.

## Bandhan Agro regression result

- Files inventoried: 14
- Pages/sections processed: 47
- Missing required fields: 0
- Missing required document categories: 0
- Automated tests passed: 10
- Remaining operator issue after applying the confirmed father-name decision: 1 genuine full-account-number inconsistency
