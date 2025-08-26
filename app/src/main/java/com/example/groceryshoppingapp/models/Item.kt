package com.example.groceryshoppingapp.models

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

@Parcelize
data class Item(
    val id: String,
    val name: String,
    val price: Double,
    val stockQuantity: Int,
    val description: String,
    val shopid: String,
    val imageUrl: String? = null
) : Parcelable
