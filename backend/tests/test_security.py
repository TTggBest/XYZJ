from zhiju.security import digest_token, hash_password, new_opaque_token, verify_password


def test_password_hash_is_argon2_and_verifies():
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


def test_opaque_tokens_are_only_looked_up_by_digest():
    token = new_opaque_token()

    assert len(token) >= 43
    assert token not in digest_token(token)
    assert digest_token(token) == digest_token(token)
