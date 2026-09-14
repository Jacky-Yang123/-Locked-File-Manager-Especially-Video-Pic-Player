
import os
import sys
import time
import itertools
import string
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.key_derivation import derive_key, verify_password
from utils.constants import SALT_SIZE

def benchmark_argon2():
    """Benchmark Argon2id hash speed."""
    print("\n[Security Benchmark]")
    print("Algorithm: Argon2id (Memory Hard)")
    print("Testing key derivation speed on this machine...")
    
    start_time = time.time()
    count = 0
    duration = 3.0 # run for 3 seconds
    
    while time.time() - start_time < duration:
        # Simulate a login attempt / crack attempt
        derive_key("password123", os.urandom(SALT_SIZE))
        count += 1
        
    actual_duration = time.time() - start_time
    hashes_per_second = count / actual_duration
    
    print(f"Hashes computed: {count}")
    print(f"Time taken: {actual_duration:.2f}s")
    print(f"Speed: {hashes_per_second:.2f} attempts/second (Single Thread)")
    
    return hashes_per_second

def estimate_crack_time(hashes_per_sec):
    """Estimate time to crack various password policies."""
    
    # Scenarios
    scenarios = [
        ("4-Digit PIN", 10**4),
        ("6-Digit PIN", 10**6),
        ("6-Char Lowercase", 26**6),
        ("8-Char Lowercase", 26**8),
        ("8-Char Complex (A-Z, a-z, 0-9)", 62**8),
    ]
    
    print("\n[Brute Force Estimation]")
    print("Assumptions: Attacker uses THIS machine (CPU).")
    print("Note: GPU cracking is faster but Argon2id resists it significantly compared to SHA256.")
    print("-" * 60)
    print(f"{'Password Type':<25} | {'Combinations':<15} | {'Max Time to Crack':<20}")
    print("-" * 60)
    
    for name, combos in scenarios:
        seconds = combos / hashes_per_sec
        time_str = format_time(seconds)
        print(f"{name:<25} | {combos:<15.0e} | {time_str:<20}")
    print("-" * 60)

def format_time(seconds):
    if seconds < 60: return f"{seconds:.1f} seconds"
    if seconds < 3600: return f"{seconds/60:.1f} minutes"
    if seconds < 86400: return f"{seconds/3600:.1f} hours"
    if seconds < 31536000: return f"{seconds/86400:.1f} days"
    years = seconds / 31536000
    if years > 1000: return "> 1000 years"
    return f"{years:.1f} years"

def actual_brute_force_demo():
    """Demonstrate a real brute force on a weak password."""
    target_password = "123"
    print(f"\n[Live Demo] Brute forcing a dummy target (Password: '{target_password}')...")
    
    # Setup Target
    salt = os.urandom(SALT_SIZE)
    target_key, _ = derive_key(target_password, salt)
    
    start_time = time.time()
    
    # Dictionary of guesses
    guesses = ["111", "222", "abc", "password", "123456", "123"]
    
    for guess in guesses:
        # print(f"Trying: {guess}...")
        key, _ = derive_key(guess, salt)
        if key == target_key:
            print(f"SUCCESS! Password found: '{guess}'")
            print(f"Time taken: {time.time() - start_time:.4f}s")
            return

    print("Failed to crack in demo list.")

if __name__ == "__main__":
    print("=== Encrypted Video Player Security Test ===")
    print("Target: Thumbnail & File Encryption (Shared Implementation)")
    
    # 1. Benchmark
    speed = benchmark_argon2()
    
    # 2. Estimation
    estimate_crack_time(speed)
    
    # 3. Live Demo
    actual_brute_force_demo()
