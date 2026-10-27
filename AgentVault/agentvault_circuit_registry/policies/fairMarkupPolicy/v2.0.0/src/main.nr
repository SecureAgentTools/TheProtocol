// Proof of fair markup, v2.0.0.
//
// Statement: the offered price is at most the committed cost plus the
// policy's maximum markup,
//     offered_price * 10000 <= total_cost * (10000 + max_markup_bps).
// The cost stays private. The circuit returns a commitment to it,
// Poseidon2(DOMAIN, total_cost, salt), so the prover is bound to one cost
// that it can later open to an auditor. The verifier checks max_markup_bps
// against the registry's policy and `context` against the offer it expects.
//
// v1.0.0 took the cap as a private input that nothing bound, so a prover
// could pick any cap that fitted. Here the cap is public.
use std::hash::poseidon2::Poseidon2;

global DOMAIN: Field = 0x74702e666169725f6d61726b75702e7632; // "tp.fair_markup.v2"
global BPS: u128 = 10000;

fn main(
    max_markup_bps: pub u32,
    offered_price: pub u64,
    context: pub Field,
    total_cost: u64,
    salt: Field,
) -> pub Field {
    assert(context != 0, "context must name the offer");
    let price_scaled = (offered_price as u128) * BPS;
    let cap_scaled = (total_cost as u128) * (BPS + (max_markup_bps as u128));
    assert(price_scaled <= cap_scaled, "price exceeds the markup cap over the committed cost");
    Poseidon2::hash([DOMAIN, total_cost as Field, salt], 3)
}

#[test]
fn test_within_cap_and_same_cost_same_commitment() {
    let a = main(3000, 1200, 7, 1000, 99);
    let b = main(3000, 1300, 8, 1000, 99);
    assert(a == b);
}

#[test]
fn test_at_cap() {
    let _ = main(3000, 1300, 7, 1000, 99);
}

#[test(should_fail_with = "price exceeds the markup cap over the committed cost")]
fn test_over_cap() {
    let _ = main(3000, 1301, 7, 1000, 99);
}

#[test(should_fail_with = "context must name the offer")]
fn test_no_context() {
    let _ = main(3000, 1200, 0, 1000, 99);
}

#[test]
fn test_salt_changes_commitment() {
    assert(main(3000, 1200, 7, 1000, 1) != main(3000, 1200, 7, 1000, 2));
}
