fn main(
    // Public inputs
    policy_parameters_hash: pub Field,
    self_attested_total_component_costs: pub u64,
    offered_price: pub u64,
    // Private inputs (witness)
    actual_markup_percentage_used: u64,
    max_markup_percentage_policy: u64
) {
    // Constraint 1: Ensure actual markup is non-negative (u64 is always >= 0, constraint implicit)

    // Constraint 2: Ensure actual markup does not exceed policy maximum
    assert(actual_markup_percentage_used <= max_markup_percentage_policy);

    // Constraint 3: Verify price consistency with costs and actual markup
    // offered_price should equal: costs * (1 + actual_markup_percentage/100)
    // Integer form: offered_price * 100 == costs * (100 + actual_markup_percentage)
    let left_side: u64 = offered_price * 100;
    let right_side: u64 = self_attested_total_component_costs * (100 + actual_markup_percentage_used);
    assert(left_side == right_side);

    // Constraint 4: Verify policy parameters hash is non-zero
    assert(policy_parameters_hash != 0);
}

#[test]
fn test_fair_markup_within_policy() {
    // Test case: 20% markup with 30% policy maximum
    // price = 1000 * 1.20 = 1200
    main(12345, 1000, 1200, 20, 30);
}

#[test]
fn test_fair_markup_at_policy_limit() {
    // Test case: 30% markup with 30% policy maximum
    // price = 1000 * 1.30 = 1300
    main(12345, 1000, 1300, 30, 30);
}

#[test(should_fail)]
fn test_markup_exceeds_policy() {
    // Test case: 35% markup with 30% policy maximum (should fail)
    main(12345, 1000, 1350, 35, 30);
}

#[test(should_fail)]
fn test_price_inconsistent_with_markup() {
    // Test case: Price doesn't match the claimed markup
    // price=1250 implies 25% markup, but claiming 20%
    main(12345, 1000, 1250, 20, 30);
}
