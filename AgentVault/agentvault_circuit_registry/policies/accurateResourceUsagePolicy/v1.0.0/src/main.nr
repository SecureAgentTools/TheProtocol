fn main(
    // Public inputs
    policy_parameters_hash: pub Field,
    avtp_transaction_id: pub Field,
    reported_resource_units_used: pub u64,
    // Private inputs (witness)
    actual_resource_units_logged: u64,
    max_allowable_discrepancy_percentage_policy: u64  // e.g., 1 for 1%
) {
    // Constraint 1: u64 inputs are always non-negative (implicit)

    // Constraint 2: Verify policy parameters hash is non-zero
    assert(policy_parameters_hash != 0);

    // Constraint 3: Verify transaction ID is non-zero
    assert(avtp_transaction_id != 0);

    // Constraint 4: Check discrepancy is within allowed percentage
    // Calculate absolute difference
    let diff: u64 = if reported_resource_units_used >= actual_resource_units_logged {
        reported_resource_units_used - actual_resource_units_logged
    } else {
        actual_resource_units_logged - reported_resource_units_used
    };

    // Handle case where actual_resource_units_logged is 0
    if actual_resource_units_logged == 0 {
        // If actual is 0, reported must also be 0
        assert(reported_resource_units_used == 0);
    } else {
        // Check: diff * 100 <= actual * max_discrepancy_percent
        let left_side: u64 = diff * 100;
        let right_side: u64 = actual_resource_units_logged * max_allowable_discrepancy_percentage_policy;
        assert(left_side <= right_side);
    }
}

#[test]
fn test_accurate_reporting() {
    // Exact match (0% discrepancy)
    main(12345, 67890, 100, 100, 1);
}

#[test]
fn test_within_allowed_discrepancy() {
    // 0.5% over with 1% allowed
    main(12345, 67890, 201, 200, 1);
}

#[test(should_fail)]
fn test_exceeds_allowed_discrepancy() {
    // 2% over with 1% allowed - should fail
    main(12345, 67890, 204, 200, 1);
}

#[test]
fn test_zero_actual_zero_reported() {
    main(12345, 67890, 0, 0, 1);
}

#[test(should_fail)]
fn test_zero_actual_nonzero_reported() {
    main(12345, 67890, 10, 0, 1);
}

#[test]
fn test_underreporting_within_limit() {
    // 0.5% under with 1% allowed
    main(12345, 67890, 199, 200, 1);
}
