/* /* */
// ---- C++ section (a nested comment for Rust) ----
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>

// Big integers: little-endian limbs in base 1e9.
typedef std::vector<uint32_t> Big;
static const uint32_t BASE = 1000000000u;

static Big add(const Big& a, const Big& b) {
    Big r;
    uint32_t carry = 0;
    size_t n = a.size() > b.size() ? a.size() : b.size();
    for (size_t i = 0; i < n; i++) {
        uint64_t s = (uint64_t)carry;
        if (i < a.size()) s += a[i];
        if (i < b.size()) s += b[i];
        r.push_back((uint32_t)(s % BASE));
        carry = (uint32_t)(s / BASE);
    }
    if (carry) r.push_back(carry);
    return r;
}

int main(int argc, char** argv) {
    long long n = argc > 1 ? atoll(argv[1]) : 0;
    Big a(1, 1), b(1, 1);
    for (long long i = 0; i < n; i++) {
        Big c = add(a, b);
        a.swap(b);
        b.swap(c);
    }
    printf("%u", a.back());
    for (size_t i = a.size() - 1; i-- > 0;) printf("%09u", a[i]);
    printf("\n");
    return 0;
}
#if 0
// */
// ---- Rust section (skipped by the C++ preprocessor) ----
const BASE: u64 = 1000000000;

fn add(a: &Vec<u64>, b: &Vec<u64>) -> Vec<u64> {
    let n = if a.len() > b.len() { a.len() } else { b.len() };
    let mut r = Vec::with_capacity(n + 1);
    let mut carry = 0u64;
    for i in 0..n {
        let mut s = carry;
        if i < a.len() { s += a[i]; }
        if i < b.len() { s += b[i]; }
        r.push(s % BASE);
        carry = s / BASE;
    }
    if carry > 0 { r.push(carry); }
    r
}

fn main() {
    let n: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    let mut a: Vec<u64> = vec![1];
    let mut b: Vec<u64> = vec![1];
    for _ in 0..n {
        let c = add(&a, &b);
        a = b;
        b = c;
    }
    let mut out = format!("{}", a[a.len() - 1]);
    for i in (0..a.len() - 1).rev() {
        out.push_str(&format!("{:09}", a[i]));
    }
    println!("{}", out);
}
/* /* */
#endif
// */
