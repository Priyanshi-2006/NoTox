export function validateUsername(username) {
  if (!username?.trim()) return "Username is required.";
  if (username.length < 3) return "Username must be at least 3 characters.";
  if (!/^[a-zA-Z0-9_]+$/.test(username)) {
    return "Username can only contain letters, numbers and underscores.";
  }
  return null;
}

export function validateEmail(email) {
  if (!email?.trim()) return "Email is required.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return "Enter a valid email address.";
  }
  return null;
}

export function validatePassword(password) {
  if (!password) return "Password is required.";
  if (password.length < 8) return "Password must be at least 8 characters.";
  return null;
}

export function validatePhoneNumber(phone) {
  if (!phone) return null; // optional field
  if (!/^\+?[1-9]\d{7,14}$/.test(phone)) {
    return "Enter a valid phone number, e.g. +911234567890.";
  }
  return null;
}
