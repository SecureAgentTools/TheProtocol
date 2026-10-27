// contentSafetyAttestation/v1.0.0
//
// Proves a content-moderating service agent rejected at least
// `min_rejection_count` of `total_samples` unsafe items within a window
// without revealing the actual rejection count.
//
// Public:   policy hash, time window hash, total samples, claimed minimum.
// Private:  actual rejection count.
// Constraints:
//   1. actual_rejection_count >= min_rejection_count
//   2. actual_rejection_count <= total_samples
//   3. policy_parameters_hash != 0
//   4. time_window_hash != 0

fn main(
    // Public inputs
    policy_parameters_hash: pub Field,
    time_window_hash: pub Field,
    total_samples: pub u64,
    min_rejection_count: pub u64,
    // Private inputs (witness)
    actual_rejection_count: u64
) {
    // Constraint 1: agent rejected at least the claimed minimum.
    assert(actual_rejection_count >= min_rejection_count);

    // Constraint 2: rejection count cannot exceed total samples.
    assert(actual_rejection_count <= total_samples);

    // Constraint 3: policy hash must be non-zero.
    assert(policy_parameters_hash != 0);

    // Constraint 4: time window hash must be non-zero.
    assert(time_window_hash != 0);
}

#[test]
fn test_above_threshold() {
    // 950 of 1000 rejected, claiming a 900 minimum.
    main(12345, 67890, 1000, 900, 950);
}

#[test]
fn test_at_threshold() {
    // Exactly at the minimum.
    main(12345, 67890, 1000, 900, 900);
}

#[test(should_fail)]
fn test_below_threshold() {
    // 850 < 900 -- should fail.
    main(12345, 67890, 1000, 900, 850);
}

#[test]
fn test_zero_samples() {
    // Edge case: zero samples + zero minimum + zero rejected -> trivially passes.
    main(12345, 67890, 0, 0, 0);
}
