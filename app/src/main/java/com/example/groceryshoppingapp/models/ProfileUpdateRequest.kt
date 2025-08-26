package com.example.groceryshoppingapp.models

data class ProfileUpdateRequest(
    val username: String,
    val full_name: String,
    val address: String,
    val phone: String,
    val email: String,
    val location: String,
    val photo_base64: String?
)
