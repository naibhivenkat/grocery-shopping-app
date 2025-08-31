package com.example.groceryshoppingapp.models

data class RegisterResponse(
    val success: Boolean,
    val message: String,
    val user: UserData? = null
)
