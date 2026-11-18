/* /* */
#include <cstdio>
#include <cstdlib>
#include <string>
#include <algorithm>

// Digits are stored least-significant first.
static std::string add(const std::string &a, const std::string &b) {
    std::string r;
    int carry = 0;
    for (size_t i = 0; i < a.size() || i < b.size() || carry; i++) {
        int s = carry;
        if (i < a.size()) s += a[i] - 48;
        if (i < b.size()) s += b[i] - 48;
        r.push_back((char)(48 + s % 10));
        carry = s / 10;
    }
    return r;
}

int main(int argc, char **argv) {
    long n = argc > 1 ? std::atol(argv[1]) : 0;
    std::string a = "1", b = "1";
    for (long i = 0; i < n; i++) {
        std::string c = add(a, b);
        a = b;
        b = c;
    }
    std::reverse(a.begin(), a.end());
    std::puts(a.c_str());
    return 0;
}
#if 0
/* */
*/

// Digits are stored least-significant first.
fn add(a: &Vec<u8>, b: &Vec<u8>) -> Vec<u8> {
    let mut r = Vec::new();
    let mut carry = 0u8;
    let mut i = 0;
    while i < a.len() || i < b.len() || carry > 0 {
        let mut s = carry;
        if i < a.len() { s += a[i]; }
        if i < b.len() { s += b[i]; }
        r.push(s % 10);
        carry = s / 10;
        i += 1;
    }
    r
}

fn main() {
    let n: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    let mut a = vec![1u8];
    let mut b = vec![1u8];
    for _ in 0..n {
        let c = add(&a, &b);
        a = b;
        b = c;
    }
    let s: String = a.iter().rev().map(|d| (d + 48) as char).collect();
    println!("{}", s);
}

/* /* */
#endif
/* */
// */
