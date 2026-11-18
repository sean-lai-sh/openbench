/*/* */
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) return 1;
    std::ios::sync_with_stdio(false);
    unsigned long long n = std::stoull(argv[1]);
    const uint64_t BASE = 1000000000000000000ULL;
    std::vector<uint64_t> a(1, 1), b(1, 1);
    for (unsigned long long step = 0; step < n; ++step) {
        if (a.size() < b.size()) a.resize(b.size(), 0);
        uint64_t carry = 0;
        for (size_t i = 0; i < b.size(); ++i) {
            uint64_t s = a[i] + b[i] + carry;
            if (s >= BASE) {
                a[i] = s - BASE;
                carry = 1;
            } else {
                a[i] = s;
                carry = 0;
            }
        }
        if (carry) a.push_back(carry);
        std::swap(a, b);
    }
    std::cout << a.back();
    for (size_t i = a.size() - 1; i-- > 0;) {
        std::cout << std::setw(18) << std::setfill('0') << a[i];
    }
    std::cout << '\n';
    return 0;
}
#if 0
*/

use std::fmt::Write;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        std::process::exit(1);
    }
    let n: u64 = args[1].trim().parse().unwrap();
    const BASE: u64 = 1000000000000000000;
    let mut a: Vec<u64> = vec![1];
    let mut b: Vec<u64> = vec![1];
    for _ in 0..n {
        if a.len() < b.len() {
            a.resize(b.len(), 0);
        }
        let mut carry: u64 = 0;
        for i in 0..b.len() {
            let s = a[i] + b[i] + carry;
            if s >= BASE {
                a[i] = s - BASE;
                carry = 1;
            } else {
                a[i] = s;
                carry = 0;
            }
        }
        if carry > 0 {
            a.push(carry);
        }
        std::mem::swap(&mut a, &mut b);
    }
    let mut out = String::new();
    write!(out, "{}", a[a.len() - 1]).unwrap();
    for i in (0..a.len() - 1).rev() {
        write!(out, "{:018}", a[i]).unwrap();
    }
    println!("{}", out);
}

const _: &str = r#" "
#endif
// "#;
