package com.example.groceryshoppingapp.models


import android.os.Parcel
import android.os.Parcelable

data class CartItem(
    val item: Item,
    var quantity: Double = 1.0,
    var unit: String = "pcs"
) : Parcelable {
    constructor(parcel: Parcel) : this(
        parcel.readParcelable(Item::class.java.classLoader)!!,
        parcel.readDouble(),
        parcel.readString() ?: "pcs"
    )

    override fun writeToParcel(parcel: Parcel, flags: Int) {
        parcel.writeParcelable(item, flags)
        parcel.writeDouble(quantity)
        parcel.writeString(unit)
    }

    override fun describeContents(): Int = 0

    companion object CREATOR : Parcelable.Creator<CartItem> {
        override fun createFromParcel(parcel: Parcel): CartItem = CartItem(parcel)
        override fun newArray(size: Int): Array<CartItem?> = arrayOfNulls(size)
    }
}
