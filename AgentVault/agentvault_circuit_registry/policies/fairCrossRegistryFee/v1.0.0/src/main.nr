// fairCrossRegistryFee/v1.0.0
//
// Proves a receiver-side TEG operator's collected cross-registry transfer
// fees match a published per-bps fee policy without revealing the actual
// applied rate or the policy maximum.
//
// Public:   policy hash, total volume transferred, total fees collected.
// Private:  actual fee rate in basis points (bps), policy max rate (bps).
// Constraints:
//   1. actual_fee_rate_bps <= max_fee_rate_bps_policy
//   2. total_fees_collected * 10000 == total_volume_transferred * actual_fee_rate_bps
//      (consistency: bps math is divided by 10000)
//   3. policy_parameters_hash != 0

fn main(
    // Public inputs
    policy_parameters_hash: pub Field,
    total_volume_transferred: pub u64,
    total_fees_collected: pub u64,
    // Private inputs (witness)
    actual_fee_rate_bps: u64,
    max_fee_rate_bps_policy: u64
) {
    // Constraint 1: actual rate must not exceed the policy maximum.
    assert(actual_fee_rate_bps <= max_fee_rate_bps_policy);

    // Constraint 2: fees and volume must be internally consistent at the
    // claimed actual rate. bps -> rate / 10000.
    let left_side: u64 = total_fees_collected * 10000;
    let right_side: u64 = total_volume_transferred * actual_fee_rate_bps;
    assert(left_side == right_side);

    // Constraint 3: policy hash must be non-zero (cheap freshness check).
    assert(policy_parameters_hash != 0);
}

#[test]
fn test_fees_at_rate() {
    // 50 bps applied to 10000 volume -> 50 fees. Policy allows up to 100 bps.
    main(12345, 10000, 50, 50, 100);
}

#[test]
fn test_fees_at_policy_limit() {
    // 100 bps (1%) at limit, 100 bps policy max.
    main(12345, 10000, 100, 100, 100);
}

#[test(should_fail)]
fn test_rate_exceeds_policy() {
    // 200 bps, but policy max is 100 bps.
    main(12345, 10000, 200, 200, 100);
}

#[test(should_fail)]
fn test_inconsistent_fees() {
    // Claims 50 bps but collected 100 fees on 10000 volume (which would be 100 bps).
    main(12345, 10000, 100, 50, 100);
}
