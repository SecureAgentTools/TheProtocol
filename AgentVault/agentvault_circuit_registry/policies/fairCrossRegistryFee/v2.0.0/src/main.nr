// Proof of fair cross-registry fees, v2.0.0.
//
// Statement: in a committed batch of up to 16 transfers, every fee is at
// most the policy's rate and the batch totals are as stated,
//     fees[i] * 10000 <= amounts[i] * max_fee_bps   for every i,
//     sum(amounts) == total_volume,  sum(fees) == total_fees.
// Unused slots are zero. The transfers stay private. The circuit returns
// Poseidon2(DOMAIN, window_ref, salt, amounts[0], fees[0], ...), so the
// batch can be opened to an auditor later.
//
// v1.0.0 proved only that total_fees / total_volume was some whole rate
// under a private cap that nothing bound.
use std::hash::poseidon2::Poseidon2;

global DOMAIN: Field = 0x74702e63726f73735f72656769737472795f6665652e7632; // "tp.cross_registry_fee.v2"
global BPS: u128 = 10000;
global N: u32 = 16;
global M: u32 = 35; // 3 + 2 * N

fn main(
    max_fee_bps: pub u32,
    window_ref: pub Field,
    total_volume: pub u64,
    total_fees: pub u64,
    amounts: [u64; N],
    fees: [u64; N],
    salt: Field,
) -> pub Field {
    assert(window_ref != 0, "window_ref must name the window");
    let mut volume: u128 = 0;
    let mut fee_sum: u128 = 0;
    let mut preimage: [Field; M] = [0; M];
    preimage[0] = DOMAIN;
    preimage[1] = window_ref;
    preimage[2] = salt;
    for i in 0..N {
        assert(
            (fees[i] as u128) * BPS <= (amounts[i] as u128) * (max_fee_bps as u128),
            "a fee exceeds the policy rate",
        );
        volume += amounts[i] as u128;
        fee_sum += fees[i] as u128;
        preimage[3 + 2 * i] = amounts[i] as Field;
        preimage[4 + 2 * i] = fees[i] as Field;
    }
    assert(volume == total_volume as u128, "amounts do not sum to total_volume");
    assert(fee_sum == total_fees as u128, "fees do not sum to total_fees");
    Poseidon2::hash(preimage, M)
}

#[test]
fn test_two_transfers_under_cap() {
    let mut a: [u64; N] = [0; N];
    let mut f: [u64; N] = [0; N];
    a[0] = 10000;
    f[0] = 50;
    a[1] = 20000;
    f[1] = 100;
    let _ = main(100, 7, 30000, 150, a, f, 3);
}

#[test(should_fail_with = "a fee exceeds the policy rate")]
fn test_one_fee_over_cap() {
    let mut a: [u64; N] = [0; N];
    let mut f: [u64; N] = [0; N];
    a[0] = 10000;
    f[0] = 101;
    let _ = main(100, 7, 10000, 101, a, f, 3);
}

#[test(should_fail_with = "fees do not sum to total_fees")]
fn test_totals_must_match() {
    let mut a: [u64; N] = [0; N];
    let mut f: [u64; N] = [0; N];
    a[0] = 10000;
    f[0] = 50;
    let _ = main(100, 7, 10000, 49, a, f, 3);
}

#[test]
fn test_commitment_binds_the_batch() {
    let mut a: [u64; N] = [0; N];
    let mut f: [u64; N] = [0; N];
    a[0] = 10000;
    f[0] = 50;
    let c1 = main(100, 7, 10000, 50, a, f, 3);
    f[0] = 40;
    let c2 = main(100, 7, 10000, 40, a, f, 3);
    assert(c1 != c2);
}
