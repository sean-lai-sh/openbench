/*
/* */
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) return 1;
    unsigned long long n = std::strtoull(argv[1], 0, 10);
    const unsigned long long base = 1000000000000000000ULL;
    std::vector<unsigned long long> a(1, 1), b(1, 1);
    for (unsigned long long step = 0; step < n; ++step) {
        if (a.size() < b.size()) a.resize(b.size(), 0);
        unsigned long long carry = 0;
        for (std::size_t i = 0; i < b.size(); ++i) {
            unsigned long long s = a[i] + b[i] + carry;
            if (s >= base) {
                a[i] = s - base;
                carry = 1;
            } else {
                a[i] = s;
                carry = 0;
            }
        }
        if (carry) a.push_back(1);
        std::swap(a, b);
    }
    std::printf("%llu", a.back());
    for (std::size_t i = a.size() - 1; i-- > 0;) {
        std::printf("%018llu", a[i]);
    }
    std::printf("\n");
    return 0;
}

namespace {
#if 0
*/
fn main() {
    let arg = match std::env::args().nth(1) {
        Some(s) => s,
        None => std::process::exit(1),
    };
    let n: u64 = arg.trim().parse().unwrap();
    let base: u64 = 1_000_000_000_000_000_000;
    let mut a: Vec<u64> = vec![1];
    let mut b: Vec<u64> = vec![1];
    for _ in 0..n {
        if a.len() < b.len() {
            a.resize(b.len(), 0);
        }
        let mut carry: u64 = 0;
        for (ai, &bi) in a.iter_mut().zip(b.iter()) {
            let s = *ai + bi + carry;
            if s >= base {
                *ai = s - base;
                carry = 1;
            } else {
                *ai = s;
                carry = 0;
            }
        }
        if carry > 0 {
            a.push(1);
        }
        std::mem::swap(&mut a, &mut b);
    }
    use std::io::Write;
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());
    write!(out, "{}", a[a.len() - 1]).unwrap();
    for &limb in a[..a.len() - 1].iter().rev() {
        write!(out, "{:018}", limb).unwrap();
    }
    writeln!(out).unwrap();
    out.flush().unwrap();
}

macro_rules! x { ($($t:tt)*) => {}; }
x! {
#endif
}
