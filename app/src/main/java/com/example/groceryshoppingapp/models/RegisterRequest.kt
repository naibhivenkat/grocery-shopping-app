package com.example.groceryshoppingapp.models

data class RegisterRequest(
    val username: String,
    val password: String,
    val userType: String  // "customer" or "shopkeeper"
)
