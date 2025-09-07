from generate_haiku_and_send import validate_and_clean_haiku

# Test cases
test_cases = [
    'Hello! World? This is a test.',
    'Forest whispers; ancient oaks stand.',
    'Wild boars roam—autumn calls.',
    'Test with "quotes" and (parentheses)!',
    'Multiple   spaces   here',
    '',
    'Normal text without special chars',
    'Mix of allowed: commas, periods. semicolons; and text'
]

print("Testing validate_and_clean_haiku function:")
print("=" * 50)

for i, test in enumerate(test_cases, 1):
    result = validate_and_clean_haiku(test)
    print(f"Test {i}: {repr(test)} -> {repr(result)}")
