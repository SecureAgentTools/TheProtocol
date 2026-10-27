// Proof of content-safety rejections, v2.0.0.
//
// Statement: in a committed log of moderated samples for a window, the
// share the filter rejected is at least the policy's minimum,
//     rejected * 10000 >= total_samples * min_rejection_bps.
// Each log entry is (sample_hash, rejected); unused slots are zero. The log
// stays private. The circuit returns Poseidon2(DOMAIN, window_ref,
// total_samples, salt, sample_hash[0], rejected[0], ...), so an auditor can
// later ask for any entry and check it. The proof binds the prover to the
// log it committed to; it cannot show which model made the decisions.
//
// v1.0.0 let the prover choose the rejection count freely.
use std::hash::poseidon2::Poseidon2;

global DOMAIN: Field = 0x74702e636f6e74656e745f7361666574792e7632; // "tp.content_safety.v2"
global N: u32 = 64;
global M: u32 = 132; // 4 + 2 * N

fn main(
    min_rejection_bps: pub u32,
    window_ref: pub Field,
    total_samples: pub u32,
    sample_hashes: [Field; N],
    rejected: [bool; N],
    salt: Field,
) -> pub Field {
    assert(window_ref != 0, "window_ref must name the window");
    assert(total_samples != 0, "the window has no samples");
    assert(total_samples <= N, "too many samples for one proof");
    let mut count: u32 = 0;
    let mut preimage: [Field; M] = [0; M];
    preimage[0] = DOMAIN;
    preimage[1] = window_ref;
    preimage[2] = total_samples as Field;
    preimage[3] = salt;
    for i in 0..N {
        if i < total_samples {
            assert(sample_hashes[i] != 0, "a sample in the window has no hash");
            if rejected[i] {
                count += 1;
            }
        } else {
            assert(sample_hashes[i] == 0, "an unused slot carries a sample");
            assert(!rejected[i], "an unused slot is marked rejected");
        }
        preimage[4 + 2 * i] = sample_hashes[i];
        preimage[5 + 2 * i] = if rejected[i] { 1 } else { 0 };
    }
    assert(
        (count as u64) * 10000 >= (total_samples as u64) * (min_rejection_bps as u64),
        "the rejection share is below the policy minimum",
    );
    Poseidon2::hash(preimage, M)
}

#[test]
fn test_share_at_minimum() {
    let mut h: [Field; N] = [0; N];
    let mut r: [bool; N] = [false; N];
    for i in 0..10 {
        h[i] = (i + 1) as Field;
    }
    for i in 0..9 {
        r[i] = true;
    }
    let _ = main(9000, 5, 10, h, r, 11);
}

#[test(should_fail_with = "the rejection share is below the policy minimum")]
fn test_share_below_minimum() {
    let mut h: [Field; N] = [0; N];
    let mut r: [bool; N] = [false; N];
    for i in 0..10 {
        h[i] = (i + 1) as Field;
    }
    for i in 0..8 {
        r[i] = true;
    }
    let _ = main(9000, 5, 10, h, r, 11);
}

#[test(should_fail_with = "an unused slot is marked rejected")]
fn test_padding_cannot_count() {
    let mut h: [Field; N] = [0; N];
    let mut r: [bool; N] = [false; N];
    h[0] = 1;
    r[0] = true;
    r[1] = true;
    let _ = main(9000, 5, 1, h, r, 11);
}

#[test(should_fail_with = "the window has no samples")]
fn test_empty_window() {
    let h: [Field; N] = [0; N];
    let r: [bool; N] = [false; N];
    let _ = main(9000, 5, 0, h, r, 11);
}
