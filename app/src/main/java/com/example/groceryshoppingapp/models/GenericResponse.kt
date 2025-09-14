package com.example.groceryshoppingapp.models

data class GenericResponse(
    val status: String?,    // e.g., "success" or "error"
    val message: String?,   // descriptive message
    val success: Boolean = status == "success"  // optional helper
)
