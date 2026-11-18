/* /* */
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) {
        return 1;
    }
    unsigned long long n = std::stoull(argv[1]);
    const std::uint32_t base = 1000000000U;
    std::vector<std::uint32_t> a(1, 1);
    std::vector<std::uint32_t> b(1, 1);
    for (unsigned long long i = 0; i < n; ++i) {
        a.resize(b.size(), 0);
        std::uint32_t carry = 0;
        for (std::size_t j = 0; j < b.size(); ++j) {
            std::uint32_t s = a[j] + b[j] + carry;
            if (s >= base) {
                s -= base;
                carry = 1;
            } else {
                carry = 0;
            }
            a[j] = s;
        }
        if (carry != 0) {
            a.push_back(carry);
        }
        std::swap(a, b);
    }
    std::cout << a.back();
    for (std::size_t j = a.size() - 1; j > 0; --j) {
        std::cout << std::setw(9) << std::setfill(char(48)) << a[j - 1];
    }
    std::cout << "\n";
    return 0;
#if 0
// */

fn main() {
    let arg = match std::env::args().nth(1) {
        Some(s) => s,
        None => std::process::exit(1),
    };
    let n: u64 = arg.trim().parse().unwrap();
    let base: u32 = 1000000000;
    let mut a: Vec<u32> = vec![1];
    let mut b: Vec<u32> = vec![1];
    for _ in 0 .. n {
        a.resize(b.len(), 0);
        let mut carry: u32 = 0;
        for j in 0 .. b.len() {
            let mut s: u32 = a[j] + b[j] + carry;
            if s >= base {
                s -= base;
                carry = 1;
            } else {
                carry = 0;
            }
            a[j] = s;
        }
        if carry != 0 {
            a.push(carry);
        }
        std::mem::swap(&mut a, &mut b);
    }
    print!("{}", a[a.len() - 1]);
    let mut j = a.len() - 1;
    while j > 0 {
        j -= 1;
        print!("{:09}", a[j]);
    }
    println!();
}

macro_rules! _cpp_endif { (# endif) => {}; }
_cpp_endif! {
#endif
}
