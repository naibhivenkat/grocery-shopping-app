package com.example.groceryshoppingapp.models

import com.google.gson.annotations.SerializedName

data class LoginResponse(
    val success: Boolean,
    val user: UserData?,
    @SerializedName("token") val token: String? // root-level token from backend
)

data class UserData(
    val username: String = "",
    val role: String = "",

    @SerializedName("shopkeeperId") val shopkeeperId: String? = null,
    @SerializedName("customerId") val customerId: String? = null,

    @SerializedName("fullName") val fullName: String? = null,
    val address: String? = null,
    val phone: String? = null,
    val email: String? = null,
    val location: String? = null,

    @SerializedName("photoBase64") val photoBase64: String? = null,
    @SerializedName("shopExists") val shopExists: Boolean? = null,
    @SerializedName("hasItems") val hasItems: Boolean? = null,

    // ✅ reuse same Shop model as in GetItemsResponse
    val shop: Shop? = null
)
