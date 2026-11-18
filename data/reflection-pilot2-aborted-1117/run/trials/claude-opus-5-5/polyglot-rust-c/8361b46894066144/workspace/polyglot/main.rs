// \
/*
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>

int main(int argc, char **argv) {
    unsigned long long n = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 0;
    const std::uint64_t base = 1000000000ULL;
    std::vector<std::uint64_t> a(1, 1), b(1, 1);
    for (unsigned long long k = 0; k < n; ++k) {
        std::vector<std::uint64_t> c;
        c.reserve(b.size() + 1);
        std::uint64_t carry = 0;
        for (std::size_t i = 0; i < b.size(); ++i) {
            std::uint64_t s = b[i] + (i < a.size() ? a[i] : 0) + carry;
            c.push_back(s % base);
            carry = s / base;
        }
        if (carry) c.push_back(carry);
        a.swap(b);
        b.swap(c);
    }
    std::printf("%llu", (unsigned long long)a.back());
    for (std::size_t i = a.size() - 1; i-- > 0;)
        std::printf("%09llu", (unsigned long long)a[i]);
    std::printf("\n");
    return 0;
}
#if 0
// \
*/
fn main() {
    let n: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    let base: u64 = 1000000000;
    let mut a: Vec<u64> = vec![1];
    let mut b: Vec<u64> = vec![1];
    for _ in 0..n {
        let mut c: Vec<u64> = Vec::with_capacity(b.len() + 1);
        let mut carry: u64 = 0;
        for i in 0..b.len() {
            let ai: u64 = if i < a.len() { a[i] } else { 0 };
            let s: u64 = b[i] + ai + carry;
            c.push(s % base);
            carry = s / base;
        }
        if carry > 0 {
            c.push(carry);
        }
        a = b;
        b = c;
    }
    let mut out = a[a.len() - 1].to_string();
    for i in (0..a.len() - 1).rev() {
        out.push_str(&format!("{:09}", a[i]));
    }
    println!("{}", out);
}
// \
/*
#endif
// \
*/
