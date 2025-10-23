package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class Item(
    val id: String,
    val name: String,
    val description: String? = null,
    val price: Double,
    @SerializedName("quantity")
    val stockQuantity: Double,
    val createdAt: String? = null,
    val createdBy: String? = null,
    @SerializedName("shopId")
    val shopid: String,

    // ✅ Support both possible keys
    @SerializedName("image")
    val imageUrl: String? = null,

    ) : Parcelable

