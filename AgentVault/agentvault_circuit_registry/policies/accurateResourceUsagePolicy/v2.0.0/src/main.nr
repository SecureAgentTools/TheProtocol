// Proof of accurate resource usage, v2.0.0.
//
// Statement: the units reported for a transaction are within the policy's
// tolerance of the units in a committed meter log,
//     |reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps,
// so an empty log allows only an empty report. The logged figure stays
// private. The circuit returns Poseidon2(DOMAIN, transaction_ref,
// logged_units, salt): a meter that publishes this commitment when the work
// runs lets a verifier check a later report against it.
//
// v1.0.0 took the logged figure and the tolerance as private inputs that
// nothing bound, so any report could be "proven" accurate.
use std::hash::poseidon2::Poseidon2;

global DOMAIN: Field = 0x74702e7265736f757263655f75736167652e7632; // "tp.resource_usage.v2"
global BPS: u128 = 10000;

fn main(
    max_discrepancy_bps: pub u32,
    transaction_ref: pub Field,
    reported_units: pub u64,
    logged_units: u64,
    salt: Field,
) -> pub Field {
    assert(transaction_ref != 0, "transaction_ref must name the transaction");
    let diff: u64 = if reported_units >= logged_units {
        reported_units - logged_units
    } else {
        logged_units - reported_units
    };
    assert(
        (diff as u128) * BPS <= (logged_units as u128) * (max_discrepancy_bps as u128),
        "report is outside the tolerance of the committed log",
    );
    Poseidon2::hash([DOMAIN, transaction_ref, logged_units as Field, salt], 4)
}

#[test]
fn test_exact() {
    let _ = main(100, 5, 100, 100, 9);
}

#[test]
fn test_within_tolerance_both_ways() {
    let _ = main(100, 5, 202, 200, 9);
    let _ = main(100, 5, 198, 200, 9);
}

#[test(should_fail_with = "report is outside the tolerance of the committed log")]
fn test_over_tolerance() {
    let _ = main(100, 5, 203, 200, 9);
}

#[test(should_fail_with = "report is outside the tolerance of the committed log")]
fn test_empty_log_nonzero_report() {
    let _ = main(100, 5, 1, 0, 9);
}

#[test]
fn test_empty_log_empty_report() {
    let _ = main(100, 5, 0, 0, 9);
}

#[test(should_fail_with = "transaction_ref must name the transaction")]
fn test_no_transaction() {
    let _ = main(100, 0, 100, 100, 9);
}

#[test]
fn test_commitment_binds_the_transaction() {
    assert(main(100, 5, 100, 100, 9) != main(100, 6, 100, 100, 9));
}
