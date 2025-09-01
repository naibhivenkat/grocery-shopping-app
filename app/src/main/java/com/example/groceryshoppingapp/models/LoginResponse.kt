package com.example.groceryshoppingapp.models

import com.google.gson.annotations.SerializedName

data class LoginResponse(
    val success: Boolean,
    val user: UserData?,
    val token: String?
)

//data class UserData(
//    val username: String,
//    val role: String,
//    @SerializedName("shopkeeperId") val shopkeeperId: String?,
//    @SerializedName("customerId") val customerId: String?,
//    @SerializedName("fullName") val fullName: String?,
//    val address: String?,
//    val phone: String?,
//    val email: String?,
//    val location: String?,
//    @SerializedName("photoBase64") val photoBase64: String?,
//    @SerializedName("shopExists") val shopExists: Boolean? = null,
//    val shop: Shops? = null // include shop object if provided
//)
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
    val shop: Shops? = null,
    val token: String? = null
)

// Matches your backend shop structure
data class Shops(
    val id: String,
    val name: String,
    val address: String? = null,
    val location: String? = null
)
