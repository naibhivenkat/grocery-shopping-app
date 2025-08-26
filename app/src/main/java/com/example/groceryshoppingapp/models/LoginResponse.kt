package com.example.groceryshoppingapp.models

import com.google.gson.annotations.SerializedName

data class LoginResponse(
    val success: Boolean,
    val user: UserData?
)

data class UserData(
    val username: String,
    val role: String,
    @SerializedName("shopkeeperId") val shopkeeperId: String?,
    @SerializedName("customerId") val customerId: String?,
    @SerializedName("fullName") val fullName: String?,
    val address: String?,
    val phone: String?,
    val email: String?,
    val location: String?,
    @SerializedName("photoBase64") val photoBase64: String?,
    @SerializedName("shopExists") val shopExists: Boolean? = null,
    val shop: Shops? = null // include shop object if provided
)

// Matches your backend shop structure
data class Shops(
    val id: String,
    val name: String,
    val address: String? = null,
    val location: String? = null
)
